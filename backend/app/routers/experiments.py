"""Experiments and runs (MLflow-compatible metadata stored in DynamoDB)."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.models import CurrentUser
from app.db.models import Experiment, ExperimentRun, JobStatus
from app.db.repositories.experiment_repo import ExperimentRepository
from app.dependencies import get_current_user, require_role
from app.middleware.tenant_scope import enforce_tenant_access, resolve_write_tenant
from app.services.audit_service import audit_service

router = APIRouter(prefix="/experiments", tags=["experiments"])

_repo = ExperimentRepository()


class ExperimentCreateRequest(BaseModel):
    name: str
    # Target tenant: required for PlatformAdmin, own-tenant-only for others.
    tenantId: Optional[str] = None
    description: Optional[str] = None
    tags: Dict[str, Any] = {}


class RunCreateRequest(BaseModel):
    jobId: Optional[str] = None
    params: Dict[str, Any] = {}
    tags: Dict[str, Any] = {}


class MetricsUpdateRequest(BaseModel):
    metrics: Dict[str, Any]


class ParamsUpdateRequest(BaseModel):
    params: Dict[str, Any]


class TagsUpdateRequest(BaseModel):
    tags: Dict[str, Any]


def _get_owned_experiment(experiment_id: str, user: CurrentUser) -> Experiment:
    exp = _repo.get_experiment(experiment_id)
    if exp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found.")
    enforce_tenant_access(user, exp.tenantId)
    return exp


@router.post("", response_model=Experiment, status_code=status.HTTP_201_CREATED)
def create_experiment(
    body: ExperimentCreateRequest,
    request: Request,
    user: CurrentUser = Depends(require_role("TenantAdmin", "DataScientist")),
) -> Experiment:
    tenant_id = resolve_write_tenant(user, body.tenantId).tenantId
    exp = Experiment(
        experimentId=str(uuid.uuid4()),
        tenantId=tenant_id,
        name=body.name,
        description=body.description,
        createdBy=user.userId,
        tags=body.tags,
    )
    _repo.create_experiment(exp)
    audit_service.record(
        user=user,
        action="experiment.create",
        resource_type="Experiment",
        resource_id=exp.experimentId,
        tenant_id=tenant_id,
        request=request,
    )
    return exp


@router.get("")
def list_experiments(
    page: int = 1, pageSize: int = 20, user: CurrentUser = Depends(get_current_user)
) -> Dict[str, Any]:
    if user.sees_all_tenants:
        items = _repo.list_all_experiments()
    else:
        items = _repo.list_experiments_by_tenant(user.tenantId)
    total = len(items)
    start = (page - 1) * pageSize
    return {
        "items": items[start : start + pageSize],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }


@router.get("/{experiment_id}")
def get_experiment(
    experiment_id: str, user: CurrentUser = Depends(get_current_user)
) -> Dict[str, Any]:
    exp = _get_owned_experiment(experiment_id, user)
    run_count = _repo.count_runs(experiment_id)
    return {**exp.model_dump(), "runCount": run_count}


@router.post("/{experiment_id}/runs", response_model=ExperimentRun, status_code=status.HTTP_201_CREATED)
def create_run(
    experiment_id: str,
    body: RunCreateRequest,
    request: Request,
    user: CurrentUser = Depends(require_role("TenantAdmin", "DataScientist")),
) -> ExperimentRun:
    exp = _get_owned_experiment(experiment_id, user)
    run = ExperimentRun(
        runId=str(uuid.uuid4()),
        experimentId=experiment_id,
        tenantId=exp.tenantId,
        jobId=body.jobId,
        status=JobStatus.RUNNING.value,
        params=body.params,
        tags=body.tags,
    )
    _repo.create_run(run)
    audit_service.record(
        user=user,
        action="run.create",
        resource_type="ExperimentRun",
        resource_id=run.runId,
        tenant_id=exp.tenantId,
        request=request,
    )
    return run


@router.get("/{experiment_id}/runs")
def list_runs(
    experiment_id: str,
    sortBy: Optional[str] = None,
    order: str = "desc",
    user: CurrentUser = Depends(get_current_user),
) -> Dict[str, Any]:
    _get_owned_experiment(experiment_id, user)
    runs = _repo.list_runs(experiment_id)
    if sortBy:
        def _sort_key(run: ExperimentRun):
            value = run.metrics.get(sortBy, run.params.get(sortBy))
            return (value is None, value if value is not None else 0)

        runs = sorted(runs, key=_sort_key, reverse=(order == "desc"))
    return {"items": runs, "total": len(runs), "page": 1, "pageSize": len(runs)}


def _get_owned_run(experiment_id: str, run_id: str, user: CurrentUser) -> ExperimentRun:
    _get_owned_experiment(experiment_id, user)
    run = _repo.get_run(experiment_id, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    return run


_RUN_WRITER_ROLES = {"PlatformAdmin", "TenantAdmin", "DataScientist"}


def _get_writable_run(experiment_id: str, run_id: str, user: CurrentUser) -> ExperimentRun:
    """Authorize a metrics/params/tags write and return the run.

    Two kinds of writers:
    - Humans (DS/TenantAdmin/PlatformAdmin): normal tenant-scoped access.
    - Machine principals (run tokens presented by training jobs): may write
      to EXACTLY the run their token was minted for — nothing else.
    """
    if user.is_machine:
        if user.machineExperimentId != experiment_id or user.machineRunId != run_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This run token is scoped to a different run.",
            )
        run = _repo.get_run(experiment_id, run_id)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
        # Belt and braces: the token's tenant must match the run's.
        enforce_tenant_access(user, run.tenantId)
        return run
    if user.role not in _RUN_WRITER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This action requires one of the following roles: "
                "DataScientist, PlatformAdmin, TenantAdmin."
            ),
        )
    return _get_owned_run(experiment_id, run_id, user)


@router.get("/{experiment_id}/runs/{run_id}", response_model=ExperimentRun)
def get_run(
    experiment_id: str, run_id: str, user: CurrentUser = Depends(get_current_user)
) -> ExperimentRun:
    return _get_owned_run(experiment_id, run_id, user)


# The three run-update endpoints accept machine principals (run tokens) in
# addition to human writers — this is the training job's "develop" loop.
@router.put("/{experiment_id}/runs/{run_id}/metrics", response_model=ExperimentRun)
def log_metrics(
    experiment_id: str,
    run_id: str,
    body: MetricsUpdateRequest,
    user: CurrentUser = Depends(get_current_user),
) -> ExperimentRun:
    run = _get_writable_run(experiment_id, run_id, user)
    run.metrics = {**run.metrics, **body.metrics}
    return _repo.update_run(run)


@router.put("/{experiment_id}/runs/{run_id}/params", response_model=ExperimentRun)
def log_params(
    experiment_id: str,
    run_id: str,
    body: ParamsUpdateRequest,
    user: CurrentUser = Depends(get_current_user),
) -> ExperimentRun:
    run = _get_writable_run(experiment_id, run_id, user)
    run.params = {**run.params, **body.params}
    return _repo.update_run(run)


@router.put("/{experiment_id}/runs/{run_id}/tags", response_model=ExperimentRun)
def set_tags(
    experiment_id: str,
    run_id: str,
    body: TagsUpdateRequest,
    user: CurrentUser = Depends(get_current_user),
) -> ExperimentRun:
    run = _get_writable_run(experiment_id, run_id, user)
    run.tags = {**run.tags, **body.tags}
    return _repo.update_run(run)
