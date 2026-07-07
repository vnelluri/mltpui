"""Training job submission, listing, status polling, cancellation, logs."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.models import CurrentUser
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
from app.db.repositories.tenant_repo import TenantRepository
from app.dependencies import get_current_user, require_role
from app.middleware.tenant_scope import enforce_tenant_access
from app.services.audit_service import audit_service
from app.services.job_service import TenantNotProvisionedError, job_service
from app.services.snowflake_service import KmsCipher

router = APIRouter(prefix="/jobs", tags=["jobs"])

_job_repo = JobRepository()
_exp_repo = ExperimentRepository()
_tenant_repo = TenantRepository()

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

    Enforces: an explicit, existing tenant (no fallback), tenant not
    suspended, and dataplane provisioning complete.
    """
    if user.is_platform_admin:
        tenant_id = body.tenantId or user.tenantId
        if not tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PlatformAdmin must specify tenantId when submitting a job.",
            )
    else:
        if not user.tenantId:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current user has no tenant assigned.",
            )
        if body.tenantId and body.tenantId != user.tenantId:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You may only submit jobs into your own tenant.",
            )
        tenant_id = user.tenantId

    tenant = _tenant_repo.get(tenant_id)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_id}' not found.",
        )
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

    secret_arn = None
    if body.snowflakeDatabase:
        # Uses a Snowflake source: retrieve the user's cached token, decrypt,
        # and re-encrypt it as a short-lived Secrets Manager entry so the
        # compute job can authenticate as the submitting user. The plaintext
        # token never touches logs, S3, or DynamoDB.
        from app.db.repositories.snowflake_token_repo import SnowflakeTokenRepository

        cache = SnowflakeTokenRepository().get(user.userId)
        if cache is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Not connected to Snowflake. Connect first via POST /snowflake/connect.",
            )
        plaintext = KmsCipher(tenant_id=tenant_id).decrypt(cache.snowflakeToken)
        secret_arn = job_service.store_job_token(
            plaintext, job.jobId, tenant_id, cache.expiresAt
        )

    try:
        job = job_service.submit(job, tenant, secret_arn)
    except TenantNotProvisionedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

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

    _job_repo.create(job)
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
