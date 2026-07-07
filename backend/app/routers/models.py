"""Model registry: register, list, transition stage, model card, archive."""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.models import CurrentUser
from app.db.models import ModelStage, ModelVersion
from app.db.repositories.experiment_repo import ExperimentRepository
from app.db.repositories.governance_repo import GovernanceRepository
from app.db.repositories.model_repo import ModelRepository
from app.dependencies import get_current_user, require_role
from app.middleware.tenant_scope import enforce_tenant_access
from app.services.audit_service import audit_service
from app.services.model_card_service import build_model_card

router = APIRouter(prefix="/models", tags=["models"])

_repo = ModelRepository()
_exp_repo = ExperimentRepository()
_gov_repo = GovernanceRepository()


class ModelRegisterRequest(BaseModel):
    name: str
    runId: Optional[str] = None
    framework: Optional[str] = None
    artifactUri: Optional[str] = None
    description: Optional[str] = None
    inputSchema: Dict[str, Any] = {}
    outputSchema: Dict[str, Any] = {}
    hasExplainer: bool = False
    driftBaselineUri: Optional[str] = None


class StageTransitionRequest(BaseModel):
    stage: str


@router.post("", response_model=ModelVersion, status_code=status.HTTP_201_CREATED)
async def register_model(
    body: ModelRegisterRequest,
    request: Request,
    user: CurrentUser = Depends(require_role("DataScientist")),
) -> ModelVersion:
    tenant_id = user.tenantId or "tenant-risk-analytics"
    next_version = _repo.latest_version_number(body.name) + 1
    mv = ModelVersion(
        modelId=str(uuid.uuid4()),
        tenantId=tenant_id,
        name=body.name,
        version=next_version,
        stage=ModelStage.NONE.value,
        runId=body.runId,
        framework=body.framework,
        artifactUri=body.artifactUri,
        description=body.description,
        inputSchema=body.inputSchema,
        outputSchema=body.outputSchema,
        hasExplainer=body.hasExplainer,
        driftBaselineUri=body.driftBaselineUri,
        registeredBy=user.userId,
    )
    _repo.create(mv)
    audit_service.record(
        user=user,
        action="model.register",
        resource_type="ModelVersion",
        resource_id=f"{mv.name}/{mv.version}",
        tenant_id=tenant_id,
        request=request,
    )
    return mv


@router.get("")
async def list_models(
    page: int = 1, pageSize: int = 20, user: CurrentUser = Depends(get_current_user)
) -> Dict[str, Any]:
    if user.sees_all_tenants:
        items = _repo.list_all()
    else:
        items = _repo.list_by_tenant(user.tenantId)
    total = len(items)
    start = (page - 1) * pageSize
    return {
        "items": items[start : start + pageSize],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }


@router.get("/{name}/versions")
async def list_versions(name: str, user: CurrentUser = Depends(get_current_user)) -> Dict[str, Any]:
    versions = _repo.list_versions(name)
    for v in versions:
        enforce_tenant_access(user, v.tenantId)
    return {"items": versions, "total": len(versions), "page": 1, "pageSize": len(versions) or 1}


def _get_owned_version(name: str, ver: int, user: CurrentUser) -> ModelVersion:
    mv = _repo.get_version(name, ver)
    if mv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model version not found.")
    enforce_tenant_access(user, mv.tenantId)
    return mv


@router.get("/{name}/versions/{ver}", response_model=ModelVersion)
async def get_version(name: str, ver: int, user: CurrentUser = Depends(get_current_user)) -> ModelVersion:
    return _get_owned_version(name, ver, user)


@router.put("/{name}/versions/{ver}/stage", response_model=ModelVersion)
async def transition_stage(
    name: str,
    ver: int,
    body: StageTransitionRequest,
    request: Request,
    user: CurrentUser = Depends(require_role("TenantAdmin")),
) -> ModelVersion:
    mv = _get_owned_version(name, ver, user)
    if body.stage == ModelStage.PRODUCTION.value:
        if not _gov_repo.has_approved_review(mv.modelId):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An approved governance review is required before promoting to Production.",
            )
    from app.db.models import utcnow_iso

    mv.stage = body.stage
    mv.promotedAt = utcnow_iso()
    mv.promotedBy = user.userId
    updated = _repo.update(mv)
    audit_service.record(
        user=user,
        action="model.stage_transition",
        resource_type="ModelVersion",
        resource_id=f"{name}/{ver}",
        tenant_id=mv.tenantId,
        details={"newStage": body.stage},
        request=request,
    )
    return updated


@router.get("/{name}/versions/{ver}/card")
async def get_model_card(name: str, ver: int, user: CurrentUser = Depends(get_current_user)) -> Dict[str, Any]:
    mv = _get_owned_version(name, ver, user)
    run = _exp_repo.get_run_by_id(mv.tenantId, mv.runId) if mv.runId else None
    reviews = _gov_repo.list_by_model(mv.modelId)
    return build_model_card(mv, run, reviews)


@router.post("/{name}/versions/{ver}/archive", response_model=ModelVersion)
async def archive_version(
    name: str,
    ver: int,
    request: Request,
    user: CurrentUser = Depends(require_role("TenantAdmin")),
) -> ModelVersion:
    mv = _get_owned_version(name, ver, user)
    mv.stage = ModelStage.ARCHIVED.value
    updated = _repo.update(mv)
    audit_service.record(
        user=user,
        action="model.archive",
        resource_type="ModelVersion",
        resource_id=f"{name}/{ver}",
        tenant_id=mv.tenantId,
        request=request,
    )
    return updated
