"""Tenant isolation helpers.

Non-PlatformAdmin (and non-MRM, for read paths) requests are scoped to the
current user's own tenant. These helpers are called from routers/services —
the enforcement is deliberately explicit at each call site (not a blanket
request middleware) because the *correct* scoping rule differs per resource
(e.g. MRM reads across all tenants but cannot write; TenantAdmin only sees
their own tenant). Centralising the *check* here keeps that logic consistent
even though it's invoked from many places.
"""
from __future__ import annotations

from fastapi import HTTPException, status

from app.auth.models import CurrentUser


def enforce_tenant_access(user: CurrentUser, tenant_id: str | None) -> None:
    """Raise 403 if ``user`` may not access resources in ``tenant_id``."""
    if not user.can_access_tenant(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this tenant's resources.",
        )


def effective_tenant_filter(user: CurrentUser, requested_tenant_id: str | None = None) -> str | None:
    """Resolve the tenant a list endpoint should be scoped to.

    - PlatformAdmin / MRM: see everything unless they explicitly filter by a
      specific tenant (``requested_tenant_id``), in which case that filter is
      honoured as-is.
    - Everyone else: always forced to their own tenant, regardless of what
      (if anything) was requested — prevents cross-tenant reads even if a
      client tampers with a query parameter.
    """
    if user.sees_all_tenants:
        return requested_tenant_id
    return user.tenantId


def require_own_tenant_write(user: CurrentUser, tenant_id: str) -> None:
    """Raise 403 unless the write target is the user's own tenant.

    Used for TenantAdmin-scoped mutations (e.g. creating a user) where
    PlatformAdmin may target any tenant but TenantAdmin may only target their
    own, even if they pass a different tenantId in the request body.
    """
    if user.is_platform_admin:
        return
    if user.tenantId != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You may only modify resources within your own tenant.",
        )
