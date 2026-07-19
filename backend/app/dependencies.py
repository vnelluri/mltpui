"""Shared FastAPI dependencies: auth resolution and role guards.

``get_current_user`` is the single place role/tenant resolution happens:

- ``AUTH_MODE=dev``: JWT validation is skipped entirely. A synthetic
  ``CurrentUser`` is built from ``DEV_USER_*`` settings (plus optional extra
  ``DEV_USER_MEMBERSHIPS`` so the membership switcher can be exercised
  locally). This branch is gated strictly by ``settings.is_dev_auth`` and can
  never activate when ``AUTH_MODE=prod``.
- ``AUTH_MODE=prod``: the bearer token is a **Cognito ID token** (issued by
  the Hosted UI after Azure AD SAML sign-in), validated against the user
  pool's JWKS. User info (email, given_name) and the user's Azure AD group
  NAMES (``custom:groups``, comma-separated) come straight from the token's
  SAML-mapped attributes. Memberships are then DERIVED from the group-name
  convention (see services/membership_service.py) — there is no mapping
  table and no local user directory; AD group membership is the sole source
  of truth, re-resolved on every request.

Membership switching: a user may hold several (role, tenant) memberships.
The active one is chosen per request via the ``X-Active-Role`` /
``X-Active-Tenant`` headers and is always validated against the derived
membership set — switching selects among what AD grants, never beyond it.
With no headers, the highest-privilege membership is the default.
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.models import MACHINE_ROLE, CurrentUser, Membership
from app.auth.cognito import TokenValidationError, validate_token
from app.config import settings
from app.services.membership_service import (
    membership_service,
    select_active_membership,
)

_bearer = HTTPBearer(auto_error=False)

ACTIVE_ROLE_HEADER = "x-active-role"
ACTIVE_TENANT_HEADER = "x-active-tenant"

NO_MEMBERSHIP_DETAIL = (
    "None of your AD groups match the platform's group-name convention. "
    "Ask your administrator to add you to the appropriate platform group."
)


def _dev_memberships() -> List[Membership]:
    """Build the synthetic dev user's membership set from DEV_USER_* vars."""
    tenant_id = settings.DEV_USER_TENANT_ID
    # PlatformAdmin and MRM are platform-wide roles — never tenant-scoped.
    if settings.DEV_USER_ROLE in {"PlatformAdmin", "MRM"}:
        tenant_id = None
    memberships = [
        Membership(
            role=settings.DEV_USER_ROLE,
            tenantId=tenant_id,
            groupName="dev-mode-synthetic",
        )
    ]
    for entry in settings.DEV_USER_MEMBERSHIPS.split(","):
        entry = entry.strip()
        if not entry:
            continue
        role, _, tenant = entry.partition(":")
        extra = Membership(
            role=role.strip(),
            tenantId=tenant.strip() or None,
            groupName="dev-mode-synthetic",
        )
        if not any(m.matches(extra.role, extra.tenantId) for m in memberships):
            memberships.append(extra)
    return memberships


def _build_user(
    request: Request,
    *,
    user_id: str,
    email: str,
    name: str,
    memberships: List[Membership],
    access_token: Optional[str],
) -> CurrentUser:
    """Select the active membership (headers) and assemble the CurrentUser."""
    requested_role = request.headers.get(ACTIVE_ROLE_HEADER)
    requested_tenant = request.headers.get(ACTIVE_TENANT_HEADER)
    active = select_active_membership(memberships, requested_role, requested_tenant)
    if active is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "The requested active role/tenant is not among your "
                "memberships."
            ),
        )
    user = CurrentUser(
        userId=user_id,
        email=email,
        name=name,
        role=active.role,
        tenantId=active.tenantId,
        memberships=memberships,
        resolvedFromGroupId=active.groupName,
        accessToken=access_token,
    )
    request.state.current_user = user
    return user


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> CurrentUser:
    # Deliberately sync (as are all route handlers): every I/O call in this
    # codebase is blocking (boto3, httpx sync), so sync defs let FastAPI run
    # them on the threadpool instead of stalling the event loop.
    # ── Machine principal: run tokens (mlrt_…) presented by training jobs ──
    # Checked before the dev bypass so the narrow machine scoping is
    # exercised identically in local dev and prod.
    from app.services.run_token_service import RUN_TOKEN_PREFIX, run_token_service

    if credentials and credentials.credentials.startswith(RUN_TOKEN_PREFIX):
        record = run_token_service.resolve(credentials.credentials)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired run token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user = CurrentUser(
            userId=f"job:{record.jobId}",
            email="",
            name=f"training job {record.jobId}",
            role=MACHINE_ROLE,
            tenantId=record.tenantId,
            memberships=[],
            resolvedFromGroupId="run-token",
            machineJobId=record.jobId,
            machineExperimentId=record.experimentId,
            machineRunId=record.runId,
            accessToken=None,
        )
        request.state.current_user = user
        return user

    # ── Dev mode: synthetic user, no JWT / Graph involved ───────────────────
    if settings.is_dev_auth:
        return _build_user(
            request,
            user_id=settings.DEV_USER_ID,
            email=settings.DEV_USER_EMAIL,
            name=settings.DEV_USER_NAME,
            memberships=_dev_memberships(),
            access_token=None,
        )

    # ── Prod mode: Cognito ID-token validation + convention-based membership
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = validate_token(token)
    except TokenValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if not payload.user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing a subject identifier.",
        )

    memberships = membership_service.memberships_from_group_names(payload.groups)
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=NO_MEMBERSHIP_DETAIL,
        )

    return _build_user(
        request,
        user_id=payload.user_id,
        email=payload.user_email or "",
        name=payload.display_name or payload.user_id,
        memberships=memberships,
        access_token=token,
    )


def require_role(*allowed_roles: str):
    """Return a dependency that 403s unless the ACTIVE role is one of
    ``allowed_roles``. PlatformAdmin is always implicitly allowed."""

    allowed = set(allowed_roles) | {"PlatformAdmin"}

    def _dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This action requires one of the following roles: "
                    f"{', '.join(sorted(allowed))}."
                ),
            )
        return user

    return _dependency


def require_any_role(roles: Iterable[str]):
    """Like :func:`require_role` but does NOT implicitly allow PlatformAdmin.

    Used where even PlatformAdmin must not bypass the check — e.g. the MRM
    governance decision (segregation of duties: the platform operator cannot
    approve models).
    """

    allowed = set(roles)

    def _dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This action requires one of the following roles: "
                    f"{', '.join(sorted(allowed))}."
                ),
            )
        return user

    return _dependency


def get_db():
    """Placeholder-free convenience dependency exposing the raw table.

    Most code goes through repositories directly, but routers that need the
    raw table (rare) can depend on this instead of importing app.db.client.
    """
    from app.db.client import get_table

    return get_table()
