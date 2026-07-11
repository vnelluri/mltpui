"""Audit log query endpoint."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends

from app.auth.models import CurrentUser
from app.db.repositories.audit_repo import AuditRepository
from app.dependencies import require_role

router = APIRouter(prefix="/audit", tags=["audit"])

_repo = AuditRepository()


@router.get("/events")
async def list_audit_events(
    page: int = 1,
    pageSize: int = 20,
    userId: Optional[str] = None,
    resourceType: Optional[str] = None,
    action: Optional[str] = None,
    startDate: Optional[str] = None,
    endDate: Optional[str] = None,
    # DataScientist gets READ access to their own tenant's trail — the audit
    # log is the paper trail of their registrations, reviews, and promotions
    # (the tenant filter below scopes everything for non-platform admins).
    user: CurrentUser = Depends(require_role("TenantAdmin", "DataScientist")),
) -> Dict[str, Any]:
    if userId:
        items, _ = _repo.list_by_user(userId, limit=1000)
    elif user.is_platform_admin:
        items, _ = _repo.list_all(limit=1000)
    else:
        items, _ = _repo.list_by_tenant(user.tenantId, limit=1000)

    if not user.is_platform_admin:
        items = [e for e in items if e.tenantId == user.tenantId]
    if resourceType:
        items = [e for e in items if e.resourceType == resourceType]
    if action:
        items = [e for e in items if e.action == action]
    if startDate:
        items = [e for e in items if e.timestamp >= startDate]
    if endDate:
        items = [e for e in items if e.timestamp <= endDate]

    total = len(items)
    start = (page - 1) * pageSize
    return {
        "items": items[start : start + pageSize],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }
