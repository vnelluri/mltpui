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


def resolve_write_tenant(user: CurrentUser, requested_tenant_id: str | None):
    """Resolve (and verify) the tenant a tenant-scoped WRITE lands in.

    - PlatformAdmin has no tenant of their own: they must name the target
      tenant explicitly — there is deliberately no fallback tenant.
    - Everyone else always writes into their own tenant; naming a different
      one is rejected rather than silently ignored.

    Returns the ``Tenant`` record (404 if it does not exist).
    """
    from app.db.repositories.tenant_repo import TenantRepository

    if user.is_platform_admin:
        tenant_id = requested_tenant_id or user.tenantId
        if not tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PlatformAdmin must specify tenantId explicitly.",
            )
    else:
        if not user.tenantId:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current user has no tenant assigned.",
            )
        if requested_tenant_id and requested_tenant_id != user.tenantId:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You may only create resources within your own tenant.",
            )
        tenant_id = user.tenantId

    tenant = TenantRepository().get(tenant_id)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{tenant_id}' not found.",
        )
    return tenant


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
