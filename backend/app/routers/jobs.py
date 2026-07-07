"""Training job submission, listing, status polling, cancellation, logs."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.models import CurrentUser
from app.config import settings
from app.db.models import (
    ComputeType,
    Experiment,
    ExperimentRun,
    JobStatus,
    ProvisioningStatus,
    Tenant,
    TenantStatus,
    TrainingJob,
    utcnow_iso,
)
from app.db.repositories.experiment_repo import ExperimentRepository
from app.db.repositories.job_repo import JobRepository
from app.dependencies import get_current_user, require_role
from app.middleware.tenant_scope import enforce_tenant_access, resolve_write_tenant
from app.services.audit_service import audit_service
from app.services.job_service import TenantNotProvisionedError, job_service
from app.services.run_token_service import run_token_service
from app.services.snowflake_service import KmsCipher

logger = logging.getLogger("ml_platform.jobs")

router = APIRouter(prefix="/jobs", tags=["jobs"])

_job_repo = JobRepository()
_exp_repo = ExperimentRepository()

# Every submitted job auto-creates a linked ExperimentRun so it always shows
# up as a comparison row in Experiments — see submit_job(). Jobs submitted
# with no explicit experiment context land in a stable, well-known per-tenant
# "default" experiment rather than each spawning a brand-new one.
_DEFAULT_EXPERIMENT_ID_PREFIX = "default-job-runs"


def _get_or_create_default_experiment(tenant_id: str, user: CurrentUser) -> Experiment:
    experiment_id = f"{_DEFAULT_EXPERIMENT_ID_PREFIX}-{tenant_id}"
    existing = _exp_repo.get_experiment(experiment_id)
    if existing is not None:
        return existing
    experiment = Experiment(
        experimentId=experiment_id,
        tenantId=tenant_id,
        name="Ad-hoc Job Runs",
        description=(
            "Auto-created — every training job submitted without an explicit "
            "experiment lands here so it always has a comparison row."
        ),
        createdBy=user.userId,
    )
    try:
        return _exp_repo.create_experiment(experiment)
    except Exception:
        # Lost a race with a concurrent submission that created it first.
        existing = _exp_repo.get_experiment(experiment_id)
        if existing is not None:
            return existing
        raise


def _token_remaining_seconds(expires_at: str) -> int:
    """Seconds until an ISO-8601 expiry; <= 0 when expired or unparseable."""
    from datetime import datetime, timezone

    cleaned = (expires_at or "").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int((dt - datetime.now(timezone.utc)).total_seconds())


def _mark_submit_failed(job: TrainingJob, secret_arn: Optional[str]) -> None:
    """Best-effort cleanup when compute dispatch fails after the platform
    record was written: delete the token secret, mark the job (and its linked
    run) failed. Never masks the original dispatch error."""
    job_service.delete_job_token(secret_arn, job.tenantId)
    job.status = JobStatus.FAILED.value
    job.completedAt = job.completedAt or utcnow_iso()
    try:
        _job_repo.update(job)
        _sync_run_with_job(job)
    except Exception:
        logger.exception(
            "Could not mark job %s failed after dispatch error.", job.jobId
        )


def _sync_run_with_job(job: TrainingJob) -> None:
    """Propagate a job's current status onto its linked ExperimentRun, if any."""
    if not job.experimentRunId:
        return
    run = _exp_repo.get_run_by_id(job.tenantId, job.experimentRunId)
    if run is None:
        return
    if run.status == job.status:
        return
    run.status = job.status
    if job.status in {
        JobStatus.SUCCEEDED.value,
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
    }:
        run.endTime = run.endTime or utcnow_iso()
    _exp_repo.update_run(run)


class JobCreateRequest(BaseModel):
    name: str
    # Target tenant. Optional for tenant-scoped users (their own tenant is
    # used and any mismatching value is rejected); required for PlatformAdmin,
    # who has no tenant of their own.
    tenantId: Optional[str] = None
    computeType: str
    framework: str
    entryPointScript: str
    s3InputPath: Optional[str] = None
    s3OutputPath: Optional[str] = None
    hyperparameters: Dict[str, Any] = {}
    instanceType: Optional[str] = None
    instanceCount: int = 1
    volumeSizeGb: int = 30
    snowflakeDatabase: Optional[str] = None
    snowflakeSchema: Optional[str] = None
    snowflakeWarehouse: Optional[str] = None
    snowflakeTable: Optional[str] = None
    snowflakeSql: Optional[str] = None
    driverMemory: Optional[str] = None
    executorMemory: Optional[str] = None
    maxExecutors: Optional[int] = None


def _resolve_target_tenant(body: JobCreateRequest, user: CurrentUser) -> Tenant:
    """Resolve and gate the tenant a job is submitted into.

    On top of the shared write-tenant resolution (explicit tenant, no
    fallback, must exist), job submission also requires the tenant to be
    active (not suspended) and its dataplane provisioning complete.
    """
    tenant = resolve_write_tenant(user, body.tenantId)
    tenant_id = tenant.tenantId
    if tenant.status != TenantStatus.ACTIVE.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tenant '{tenant_id}' is suspended — job submission is disabled.",
        )
    if tenant.provisioningStatus != ProvisioningStatus.ACTIVE.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Tenant '{tenant_id}' compute is not provisioned yet "
                f"(status: {tenant.provisioningStatus}). Try again once "
                "provisioning completes."
            ),
        )
    return tenant


@router.post("", response_model=TrainingJob, status_code=status.HTTP_201_CREATED)
async def submit_job(
    body: JobCreateRequest,
    request: Request,
    user: CurrentUser = Depends(require_role("DataScientist")),
) -> TrainingJob:
    tenant = _resolve_target_tenant(body, user)
    tenant_id = tenant.tenantId

    job = TrainingJob(
        jobId=str(uuid.uuid4()),
        tenantId=tenant_id,
        userId=user.userId,
        name=body.name,
        status=JobStatus.QUEUED.value,
        framework=body.framework,
        entryPointScript=body.entryPointScript,
        s3InputPath=body.s3InputPath,
        s3OutputPath=body.s3OutputPath,
        computeType=body.computeType,
        hyperparameters=body.hyperparameters,
        instanceType=body.instanceType,
        instanceCount=body.instanceCount,
        volumeSizeGb=body.volumeSizeGb,
        snowflakeDatabase=body.snowflakeDatabase,
        snowflakeSchema=body.snowflakeSchema,
        snowflakeWarehouse=body.snowflakeWarehouse,
        snowflakeTable=body.snowflakeTable,
        snowflakeSql=body.snowflakeSql,
        driverMemory=body.driverMemory,
        executorMemory=body.executorMemory,
        maxExecutors=body.maxExecutors,
    )

    # Uses a Snowflake source: validate the connection and decrypt the cached
    # token BEFORE creating any record or external resource, so validation
    # failures (no cached token) leave nothing behind. The plaintext token
    # never touches logs, S3, or DynamoDB.
    snowflake_token: Optional[str] = None
    snowflake_token_expires_at: Optional[str] = None
    if body.snowflakeDatabase:
        from app.db.repositories.snowflake_token_repo import SnowflakeTokenRepository

        cache = SnowflakeTokenRepository().get(user.userId)
        if cache is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Not connected to Snowflake. Connect first via POST /snowflake/connect.",
            )
        # Token lifetime (~1h) is far shorter than a job's max runtime: the
        # job consumes the token for its INITIAL data read, so what matters
        # is enough runway to get scheduled and start reading. Fail fast at
        # submission on an expired/about-to-expire token instead of letting
        # the job die confusingly mid-startup.
        remaining = _token_remaining_seconds(cache.expiresAt)
        min_runway = settings.SNOWFLAKE_TOKEN_MIN_REMAINING_MINUTES * 60
        if remaining < min_runway:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Your Snowflake token "
                    + ("has expired" if remaining <= 0 else f"expires in {remaining // 60} minute(s)")
                    + f" — at least {settings.SNOWFLAKE_TOKEN_MIN_REMAINING_MINUTES} minutes are "
                    "required at submission. Reconnect via POST /snowflake/connect and resubmit."
                ),
            )
        snowflake_token = KmsCipher(tenant_id=tenant_id).decrypt(cache.snowflakeToken)
        snowflake_token_expires_at = cache.expiresAt

    # Auto-create a linked ExperimentRun so this job always has a comparison
    # row in Experiments — the training script can enrich it later via
    # PUT /experiments/{id}/runs/{runId}/metrics|params|tags.
    experiment = _get_or_create_default_experiment(tenant_id, user)
    run = ExperimentRun(
        runId=str(uuid.uuid4()),
        experimentId=experiment.experimentId,
        tenantId=tenant_id,
        jobId=job.jobId,
        status=job.status,
        params={k: str(v) for k, v in job.hyperparameters.items()},
        tags={"framework": job.framework, "computeType": job.computeType},
        artifactUri=job.s3OutputPath,
    )
    _exp_repo.create_run(run)
    job.experimentId = experiment.experimentId
    job.experimentRunId = run.runId

    # Persist the platform record BEFORE dispatching to compute: a crash after
    # dispatch can no longer orphan a live EMR/SageMaker run the platform
    # doesn't know about. If dispatch fails, the record is marked failed and
    # the token secret is cleaned up.
    _job_repo.create(job)

    secret_arn = None
    try:
        # Machine identity for the run: the training job authenticates back
        # to this API (metrics/params/tags on its own run) with a run token
        # delivered via the per-job secret — never through the API response.
        secret_payload: Dict[str, Any] = {
            "run_token": run_token_service.mint(job),
            "experimentId": job.experimentId,
            "runId": job.experimentRunId,
        }
        if snowflake_token is not None:
            secret_payload["snowflake_token"] = snowflake_token
            secret_payload["snowflakeExpiresAt"] = snowflake_token_expires_at
        secret_arn = job_service.store_job_secret(job.jobId, tenant_id, secret_payload)
        job = job_service.submit(job, tenant, secret_arn)
    except TenantNotProvisionedError as exc:
        _mark_submit_failed(job, secret_arn)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except Exception as exc:
        _mark_submit_failed(job, secret_arn)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to dispatch job to the compute backend: {exc}",
        ) from exc

    _job_repo.update(job)
    audit_service.record(
        user=user,
        action="job.submit",
        resource_type="TrainingJob",
        resource_id=job.jobId,
        tenant_id=tenant_id,
        details={"computeType": job.computeType, "framework": job.framework},
        request=request,
    )
    return job


@router.get("")
async def list_jobs(
    page: int = 1,
    pageSize: int = 20,
    status_filter: Optional[str] = None,
    framework: Optional[str] = None,
    computeType: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
) -> Dict[str, Any]:
    if user.is_platform_admin:
        items, _ = _job_repo.list_all(limit=1000)
    else:
        items, _ = _job_repo.list_by_tenant(user.tenantId, limit=1000)

    updated_items = []
    for j in items:
        # job_service.live_status mutates its argument in place and returns
        # the same reference, so the previous status must be captured first
        # — comparing recomputed.status to j.status afterwards would always
        # be comparing the object to itself.
        previous_status = j.status
        recomputed = job_service.live_status(j)
        if recomputed.status != previous_status:
            _job_repo.update(recomputed)
            _sync_run_with_job(recomputed)
        updated_items.append(recomputed)
    items = updated_items
    if status_filter:
        items = [j for j in items if j.status == status_filter]
    if framework:
        items = [j for j in items if j.framework == framework]
    if computeType:
        items = [j for j in items if j.computeType == computeType]

    total = len(items)
    start = (page - 1) * pageSize
    return {
        "items": items[start : start + pageSize],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }


def _get_owned_job(job_id: str, user: CurrentUser) -> TrainingJob:
    job = _job_repo.get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    enforce_tenant_access(user, job.tenantId)
    return job


@router.get("/{job_id}", response_model=TrainingJob)
async def get_job(job_id: str, user: CurrentUser = Depends(get_current_user)) -> TrainingJob:
    job = _get_owned_job(job_id, user)
    previous_status = job.status
    updated = job_service.live_status(job)
    if updated.status != previous_status:
        _job_repo.update(updated)
        _sync_run_with_job(updated)
    return updated


@router.post("/{job_id}/cancel", response_model=TrainingJob)
async def cancel_job(
    job_id: str,
    request: Request,
    user: CurrentUser = Depends(require_role("TenantAdmin", "DataScientist")),
) -> TrainingJob:
    job = _get_owned_job(job_id, user)
    if job.status in {JobStatus.SUCCEEDED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job is already in a terminal state: {job.status}",
        )
    cancelled = job_service.cancel(job)
    _job_repo.update(cancelled)
    _sync_run_with_job(cancelled)
    audit_service.record(
        user=user,
        action="job.cancel",
        resource_type="TrainingJob",
        resource_id=job_id,
        tenant_id=job.tenantId,
        request=request,
    )
    return cancelled


@router.get("/{job_id}/logs")
async def get_job_logs(job_id: str, user: CurrentUser = Depends(get_current_user)) -> Dict[str, str]:
    job = _get_owned_job(job_id, user)
    return {"logStreamUrl": job_service.log_stream_url(job)}
