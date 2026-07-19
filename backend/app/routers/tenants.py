"""Tenant management. Create/list/suspend/reactivate are PlatformAdmin
only; get/update/metrics are also reachable by TenantAdmin for their own
tenant."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.models import CurrentUser
from app.config import settings
from app.db.models import ProvisioningStatus, Tenant, TenantStatus, utcnow_iso
from app.db.repositories.job_repo import JobRepository
from app.db.repositories.model_repo import ModelRepository
from app.db.repositories.tenant_repo import TenantRepository
from app.dependencies import require_role
from app.middleware.tenant_scope import enforce_tenant_access
from app.services.audit_service import audit_service
from app.services.dataplane_service import dataplane_client
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
#
# Max length 30: the dataplane execution role name is
# "{name_prefix}-tenant-{tenantId}-exec" ("ml-platform-tenant-…-exec" = 24
# fixed chars), and IAM role names cap at 64 — a longer slug would pass
# validation here and then fail terraform apply in the provisioning pipeline.
_TENANT_ID_MAX = 30
_TENANT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,28}[a-z0-9]$")


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
def create_tenant(
    body: TenantCreateRequest,
    request: Request,
    user: CurrentUser = Depends(require_role("PlatformAdmin")),
) -> Tenant:
    tenant_id = body.tenantId.strip().lower()
    if not _TENANT_ID_RE.match(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"tenantId must be a lowercase slug (letters, digits, hyphens; "
                f"3-{_TENANT_ID_MAX} chars) — it appears in the AD group names "
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
def complete_provisioning(
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
def list_tenants(
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
def get_tenant(
    tenant_id: str, user: CurrentUser = Depends(require_role("TenantAdmin"))
) -> Tenant:
    tenant = _tenant_repo.get(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    enforce_tenant_access(user, tenant_id)
    return tenant


@router.put("/{tenant_id}", response_model=Tenant)
def update_tenant(
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
def suspend_tenant(
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
def reactivate_tenant(
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
def tenant_metrics(
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


# Rough sizing for the phase-1 utilization ESTIMATE: EMR Serverless default
# workers are 4 vCPU. Real per-application worker counts come from CloudWatch
# (phase 2); until then utilization is derived from the running jobs' own
# executor demand and labeled estimated.
_EST_VCPU_PER_WORKER = 4
_MOCK_MAX_VCPU = 400


@router.get("/{tenant_id}/compute-stats")
def tenant_compute_stats(
    tenant_id: str,
    # DataScientist may read it too — the DS dashboard shows a slim version.
    user: CurrentUser = Depends(require_role("TenantAdmin", "DataScientist")),
) -> Dict[str, Any]:
    """Cluster-level view of the tenant's EMR Serverless application:
    platform-side job counts, application state + configured max capacity,
    and an estimated utilization percentage."""
    tenant = _tenant_repo.get(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    enforce_tenant_access(user, tenant_id)

    from app.services.job_service import job_service

    jobs, _ = _job_repo.list_by_tenant(tenant_id, limit=1000)
    # Resolve live statuses WITHOUT persisting — counts must reflect mock
    # progression even when the Jobs page isn't polling, but this endpoint
    # stays read-only (the next jobs poll persists any transitions).
    jobs = [job_service.live_status(j) for j in jobs]
    running_jobs = [j for j in jobs if j.status == "running"]
    queued_count = sum(1 for j in jobs if j.status == "queued")

    # Application state + configured max capacity (one cheap API call).
    app_state: str = "UNKNOWN"
    max_vcpu: Optional[int] = None
    if settings.EMR_MOCK_MODE:
        app_state, max_vcpu = "STARTED", _MOCK_MAX_VCPU
    elif tenant.emrApplicationId:
        try:
            resp = dataplane_client("emr-serverless", tenant_id).get_application(
                applicationId=tenant.emrApplicationId
            )
            application = resp.get("application", {})
            app_state = application.get("state", "UNKNOWN")
            # maximumCapacity.cpu is a string like "400 vCPU".
            cpu_text = str((application.get("maximumCapacity") or {}).get("cpu", ""))
            digits = re.search(r"\d+", cpu_text)
            max_vcpu = int(digits.group()) if digits else None
        except Exception:
            pass  # stats degrade gracefully; state stays UNKNOWN

    allocated_vcpu = sum(
        (j.maxExecutors or j.instanceCount or 1) * _EST_VCPU_PER_WORKER for j in running_jobs
    )
    utilization = (
        min(100, round(allocated_vcpu / max_vcpu * 100)) if max_vcpu and allocated_vcpu else 0
    )
    return {
        "tenantId": tenant_id,
        "applicationId": tenant.emrApplicationId,
        "applicationState": app_state,
        "runningJobs": len(running_jobs),
        "queuedJobs": queued_count,
        "maxVcpu": max_vcpu,
        "allocatedVcpuEstimate": allocated_vcpu,
        "utilizationPct": utilization if max_vcpu else None,
        # Honest labeling: derived from job executor demand, not CloudWatch.
        "estimated": True,
    }
