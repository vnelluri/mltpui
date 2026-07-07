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
from app.middleware.tenant_scope import enforce_tenant_access, resolve_write_tenant
from app.services.audit_service import audit_service
from app.services.model_card_service import build_model_card

router = APIRouter(prefix="/models", tags=["models"])

_repo = ModelRepository()
_exp_repo = ExperimentRepository()
_gov_repo = GovernanceRepository()


def _scope_tenant(user: CurrentUser, requested_tenant_id: Optional[str]) -> str:
    """Resolve which tenant's model namespace a name-based endpoint targets.

    Model names are namespaced per tenant, so cross-tenant roles
    (PlatformAdmin/MRM) must say which tenant they mean via the ``tenantId``
    query parameter; tenant-scoped users are always pinned to their own.
    """
    if user.sees_all_tenants:
        tenant_id = requested_tenant_id or user.tenantId
        if not tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Model names are tenant-scoped: cross-tenant roles must "
                    "pass the tenantId query parameter."
                ),
            )
        return tenant_id
    if not user.tenantId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current user has no tenant assigned.",
        )
    if requested_tenant_id and requested_tenant_id != user.tenantId:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You may only access models within your own tenant.",
        )
    return user.tenantId


class ModelRegisterRequest(BaseModel):
    name: str
    # Target tenant: required for PlatformAdmin (who has no tenant of their
    # own); tenant-scoped users may omit it and any mismatch is rejected.
    tenantId: Optional[str] = None
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
    tenant_id = resolve_write_tenant(user, body.tenantId).tenantId
    next_version = _repo.latest_version_number(tenant_id, body.name) + 1
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
async def list_versions(
    name: str,
    tenantId: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
) -> Dict[str, Any]:
    tenant_id = _scope_tenant(user, tenantId)
    versions = _repo.list_versions(tenant_id, name)
    for v in versions:
        enforce_tenant_access(user, v.tenantId)
    return {"items": versions, "total": len(versions), "page": 1, "pageSize": len(versions) or 1}


def _get_owned_version(
    name: str, ver: int, user: CurrentUser, requested_tenant_id: Optional[str]
) -> ModelVersion:
    tenant_id = _scope_tenant(user, requested_tenant_id)
    mv = _repo.get_version(tenant_id, name, ver)
    if mv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model version not found.")
    enforce_tenant_access(user, mv.tenantId)
    return mv


@router.get("/{name}/versions/{ver}", response_model=ModelVersion)
async def get_version(
    name: str,
    ver: int,
    tenantId: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
) -> ModelVersion:
    return _get_owned_version(name, ver, user, tenantId)


@router.put("/{name}/versions/{ver}/stage", response_model=ModelVersion)
async def transition_stage(
    name: str,
    ver: int,
    body: StageTransitionRequest,
    request: Request,
    tenantId: Optional[str] = None,
    user: CurrentUser = Depends(require_role("TenantAdmin")),
) -> ModelVersion:
    mv = _get_owned_version(name, ver, user, tenantId)
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
async def get_model_card(
    name: str,
    ver: int,
    tenantId: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
) -> Dict[str, Any]:
    mv = _get_owned_version(name, ver, user, tenantId)
    run = _exp_repo.get_run_by_id(mv.tenantId, mv.runId) if mv.runId else None
    reviews = _gov_repo.list_by_model(mv.modelId)
    return build_model_card(mv, run, reviews)


@router.post("/{name}/versions/{ver}/archive", response_model=ModelVersion)
async def archive_version(
    name: str,
    ver: int,
    request: Request,
    tenantId: Optional[str] = None,
    user: CurrentUser = Depends(require_role("TenantAdmin")),
) -> ModelVersion:
    mv = _get_owned_version(name, ver, user, tenantId)
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
