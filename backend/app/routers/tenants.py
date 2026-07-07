"""Tenant management. Create/list/suspend/reactivate are PlatformAdmin
only; get/update/metrics are also reachable by TenantAdmin for their own
tenant."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.models import CurrentUser
from app.db.models import ProvisioningStatus, Tenant, TenantStatus, utcnow_iso
from app.db.repositories.job_repo import JobRepository
from app.db.repositories.model_repo import ModelRepository
from app.db.repositories.tenant_repo import TenantRepository
from app.dependencies import require_role
from app.middleware.tenant_scope import enforce_tenant_access
from app.services.audit_service import audit_service
from app.services.tenant_provisioning_service import tenant_provisioning_service

router = APIRouter(prefix="/tenants", tags=["tenants"])

_tenant_repo = TenantRepository()
_job_repo = JobRepository()
_model_repo = ModelRepository()


# The tenant ID is the KEY that ties everything together: it is the segment
# that appears in the Entra group names (myapp-{tenantId}-{role}), the S3
# prefix, and the dataplane resource names — so it is chosen by the admin at
# creation (never generated) and must be a stable lowercase slug. The Tenant
# record then maps this ID to the human display name and config.
_TENANT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")


class TenantCreateRequest(BaseModel):
    tenantId: str
    name: str
    computeQuotaVcpuHours: int = 1000
    allowedFrameworks: List[str] = ["pytorch", "tensorflow", "sklearn", "xgboost"]


class TenantUpdateRequest(BaseModel):
    name: Optional[str] = None
    computeQuotaVcpuHours: Optional[int] = None
    allowedFrameworks: Optional[List[str]] = None
    emrApplicationId: Optional[str] = None
    sagemakerDomainId: Optional[str] = None
    executionRoleArn: Optional[str] = None


class ProvisioningWriteBackRequest(BaseModel):
    """Result reported by the dataplane provisioning pipeline."""

    status: str  # "active" | "failed"
    emrApplicationId: Optional[str] = None
    sagemakerDomainId: Optional[str] = None
    executionRoleArn: Optional[str] = None
    kmsKeyArn: Optional[str] = None
    s3BucketName: Optional[str] = None


@router.post("", response_model=Tenant, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreateRequest,
    request: Request,
    user: CurrentUser = Depends(require_role("PlatformAdmin")),
) -> Tenant:
    tenant_id = body.tenantId.strip().lower()
    if not _TENANT_ID_RE.match(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "tenantId must be a lowercase slug (letters, digits, hyphens; "
                "3-50 chars) — it appears in the AD group names "
                "(myapp-<tenantId>-<role>) and S3 prefixes."
            ),
        )
    if _tenant_repo.get(tenant_id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant '{tenant_id}' already exists.",
        )
    tenant = Tenant(
        tenantId=tenant_id,
        name=body.name,
        status=TenantStatus.ACTIVE.value,
        createdBy=user.userId,
        computeQuotaVcpuHours=body.computeQuotaVcpuHours,
        allowedFrameworks=body.allowedFrameworks,
    )
    # Dataplane resources are never created at request time: in mock mode the
    # tenant is self-provisioned with mock IDs; otherwise a provisioning event
    # is emitted and the tenant stays "pending" until the IaC pipeline reports
    # back via PUT /tenants/{id}/provisioning.
    tenant = tenant_provisioning_service.provision(tenant, requested_by=user.userId)
    _tenant_repo.create(tenant)
    audit_service.record(
        user=user,
        action="tenant.create",
        resource_type="Tenant",
        resource_id=tenant_id,
        tenant_id=tenant_id,
        details={"provisioningStatus": tenant.provisioningStatus},
        request=request,
    )
    return tenant


@router.put("/{tenant_id}/provisioning", response_model=Tenant)
async def complete_provisioning(
    tenant_id: str,
    body: ProvisioningWriteBackRequest,
    request: Request,
    user: CurrentUser = Depends(require_role("PlatformAdmin")),
) -> Tenant:
    """Write-back endpoint for the dataplane provisioning pipeline (also
    usable by a PlatformAdmin to record manually provisioned resources)."""
    if body.status not in {
        ProvisioningStatus.ACTIVE.value,
        ProvisioningStatus.FAILED.value,
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="status must be 'active' or 'failed'.",
        )
    tenant = _tenant_repo.get(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    if body.status == ProvisioningStatus.ACTIVE.value and not (
        (body.emrApplicationId or tenant.emrApplicationId)
        and (body.executionRoleArn or tenant.executionRoleArn)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Marking provisioning active requires emrApplicationId and "
                "executionRoleArn."
            ),
        )
    for field in ("emrApplicationId", "sagemakerDomainId", "executionRoleArn", "kmsKeyArn", "s3BucketName"):
        value = getattr(body, field)
        if value is not None:
            setattr(tenant, field, value)
    tenant.provisioningStatus = body.status
    updated = _tenant_repo.update(tenant)
    audit_service.record(
        user=user,
        action="tenant.provisioning_writeback",
        resource_type="Tenant",
        resource_id=tenant_id,
        tenant_id=tenant_id,
        details={"provisioningStatus": body.status},
        request=request,
    )
    return updated


@router.get("")
async def list_tenants(
    page: int = 1,
    pageSize: int = 20,
    user: CurrentUser = Depends(require_role("PlatformAdmin")),
) -> Dict[str, Any]:
    items, _ = _tenant_repo.list_all(limit=500)
    total = len(items)
    start = (page - 1) * pageSize
    return {
        "items": items[start : start + pageSize],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }


@router.get("/{tenant_id}", response_model=Tenant)
async def get_tenant(
    tenant_id: str, user: CurrentUser = Depends(require_role("TenantAdmin"))
) -> Tenant:
    tenant = _tenant_repo.get(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    enforce_tenant_access(user, tenant_id)
    return tenant


@router.put("/{tenant_id}", response_model=Tenant)
async def update_tenant(
    tenant_id: str,
    body: TenantUpdateRequest,
    request: Request,
    user: CurrentUser = Depends(require_role("TenantAdmin")),
) -> Tenant:
    tenant = _tenant_repo.get(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    enforce_tenant_access(user, tenant_id)
    updates = body.model_dump(exclude_unset=True)
    if not user.is_platform_admin:
        # TenantAdmin may only tune quota/frameworks — not compute endpoints.
        updates.pop("emrApplicationId", None)
        updates.pop("sagemakerDomainId", None)
        updates.pop("executionRoleArn", None)
    for field, value in updates.items():
        setattr(tenant, field, value)
    updated = _tenant_repo.update(tenant)
    audit_service.record(
        user=user,
        action="tenant.update",
        resource_type="Tenant",
        resource_id=tenant_id,
        tenant_id=tenant_id,
        request=request,
    )
    return updated


@router.post("/{tenant_id}/suspend", response_model=Tenant)
async def suspend_tenant(
    tenant_id: str,
    request: Request,
    user: CurrentUser = Depends(require_role("PlatformAdmin")),
) -> Tenant:
    tenant = _tenant_repo.set_status(tenant_id, TenantStatus.SUSPENDED.value)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    audit_service.record(
        user=user,
        action="tenant.suspend",
        resource_type="Tenant",
        resource_id=tenant_id,
        tenant_id=tenant_id,
        request=request,
    )
    return tenant


@router.post("/{tenant_id}/reactivate", response_model=Tenant)
async def reactivate_tenant(
    tenant_id: str,
    request: Request,
    user: CurrentUser = Depends(require_role("PlatformAdmin")),
) -> Tenant:
    tenant = _tenant_repo.set_status(tenant_id, TenantStatus.ACTIVE.value)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    audit_service.record(
        user=user,
        action="tenant.reactivate",
        resource_type="Tenant",
        resource_id=tenant_id,
        tenant_id=tenant_id,
        request=request,
    )
    return tenant


@router.get("/{tenant_id}/metrics")
async def tenant_metrics(
    tenant_id: str, user: CurrentUser = Depends(require_role("TenantAdmin"))
) -> Dict[str, Any]:
    tenant = _tenant_repo.get(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    enforce_tenant_access(user, tenant_id)
    jobs, _ = _job_repo.list_by_tenant(tenant_id, limit=1000)
    registered_models = len(_model_repo.list_by_tenant(tenant_id))
    running_jobs = sum(1 for j in jobs if j.status in {"queued", "running"})
    compute_hours_used = 0.0
    for job in jobs:
        if job.durationSeconds:
            compute_hours_used += (job.durationSeconds / 3600.0) * max(job.instanceCount, 1)
    return {
        "tenantId": tenant_id,
        "jobCount": len(jobs),
        "computeHoursUsed": round(compute_hours_used, 2),
        "computeQuotaVcpuHours": tenant.computeQuotaVcpuHours,
        "runningJobs": running_jobs,
        "registeredModels": registered_models,
        "jobsByStatus": {
            s: sum(1 for j in jobs if j.status == s)
            for s in {"queued", "running", "succeeded", "failed", "cancelled"}
        },
    }
