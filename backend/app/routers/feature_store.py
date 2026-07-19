"""Feature Store preview — see services/feature_store_service.py for what is
and isn't real here. The FeatureView registry is a genuine DynamoDB-backed
entity; the batch/online preview data is entirely synthetic."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.models import CurrentUser
from app.db.models import FeatureView, utcnow_iso
from app.db.repositories.feature_view_repo import FeatureViewRepository
from app.dependencies import get_current_user, require_role
from app.middleware.tenant_scope import enforce_tenant_access, resolve_write_tenant
from app.services.audit_service import audit_service
from app.services.feature_store_service import (
    generate_offline_preview,
    generate_online_preview,
)

router = APIRouter(prefix="/feature-store", tags=["feature-store"])

_repo = FeatureViewRepository()


class FeatureDefRequest(BaseModel):
    name: str
    dtype: str = "string"  # string | int64 | float | bool | timestamp


class FeatureViewCreateRequest(BaseModel):
    name: str
    # Target tenant: required for PlatformAdmin, own-tenant-only for others.
    tenantId: Optional[str] = None
    description: Optional[str] = None
    entityColumn: str
    features: List[FeatureDefRequest]
    sourceTable: str
    experimentId: Optional[str] = None


@router.post("/views", response_model=FeatureView, status_code=status.HTTP_201_CREATED)
def create_feature_view(
    body: FeatureViewCreateRequest,
    request: Request,
    user: CurrentUser = Depends(require_role("DataScientist")),
) -> FeatureView:
    tenant_id = resolve_write_tenant(user, body.tenantId).tenantId
    fv = FeatureView(
        featureViewId=str(uuid.uuid4()),
        tenantId=tenant_id,
        name=body.name,
        description=body.description,
        entityColumn=body.entityColumn,
        features=[f.model_dump() for f in body.features],
        sourceTable=body.sourceTable,
        experimentId=body.experimentId,
        createdBy=user.userId,
    )
    _repo.create(fv)
    audit_service.record(
        user=user,
        action="feature_view.create",
        resource_type="FeatureView",
        resource_id=fv.featureViewId,
        tenant_id=tenant_id,
        request=request,
    )
    return fv


@router.get("/views")
def list_feature_views(
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


def _get_owned_feature_view(feature_view_id: str, user: CurrentUser) -> FeatureView:
    fv = _repo.get(feature_view_id)
    if fv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feature view not found.")
    enforce_tenant_access(user, fv.tenantId)
    return fv


@router.get("/views/{feature_view_id}", response_model=FeatureView)
def get_feature_view(
    feature_view_id: str, user: CurrentUser = Depends(get_current_user)
) -> FeatureView:
    return _get_owned_feature_view(feature_view_id, user)


@router.get("/views/{feature_view_id}/preview")
def preview_feature_view(
    feature_view_id: str, user: CurrentUser = Depends(get_current_user)
) -> Dict[str, Any]:
    fv = _get_owned_feature_view(feature_view_id, user)
    return {
        "offline": generate_offline_preview(fv.entityColumn, fv.features),
        "online": generate_online_preview(fv.entityColumn, fv.features),
    }


@router.post("/views/{feature_view_id}/materialize", response_model=FeatureView)
def materialize_feature_view(
    feature_view_id: str,
    request: Request,
    user: CurrentUser = Depends(require_role("TenantAdmin", "DataScientist")),
) -> FeatureView:
    fv = _get_owned_feature_view(feature_view_id, user)
    fv.lastMaterializedAt = utcnow_iso()
    updated = _repo.update(fv)
    audit_service.record(
        user=user,
        action="feature_view.materialize",
        resource_type="FeatureView",
        resource_id=feature_view_id,
        tenant_id=fv.tenantId,
        request=request,
    )
    return updated
