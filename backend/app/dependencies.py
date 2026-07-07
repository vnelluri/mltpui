"""Shared FastAPI dependencies: auth resolution and role guards.

``get_current_user`` is the single place tenancy/role resolution happens:

- ``AUTH_MODE=dev``: JWT validation is skipped entirely. A synthetic
  ``CurrentUser`` is built from ``DEV_USER_*`` settings. No DynamoDB
  GroupMapping lookup is performed. This branch is gated strictly by
  ``settings.is_dev_auth`` and can never activate when ``AUTH_MODE=prod``.
- ``AUTH_MODE=prod``: the bearer token is validated against Entra ID's JWKS,
  the ``groups`` claim is extracted, and resolved against ``GroupMapping``
  via :class:`GroupResolverService`. The resolution always re-runs from the
  JWT on every request (never trusts a cached role, and nothing is persisted
  — Entra ID + GroupMapping is the sole source of truth for identity, role,
  and tenant; there is deliberately no local user directory to keep in
  sync). If no group maps to a role, a 403 is raised with a message
  instructing the user to contact their platform administrator.
"""
from __future__ import annotations

from typing import Iterable, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.models import CurrentUser
from app.auth.oidc import TokenValidationError, validate_token
from app.config import settings
from app.services.group_resolver_service import GroupResolverService

_bearer = HTTPBearer(auto_error=False)

_group_resolver = GroupResolverService()

NO_GROUP_MAPPING_DETAIL = (
    "No group mapping found. Contact your platform administrator."
)


def _dev_current_user() -> CurrentUser:
    tenant_id = settings.DEV_USER_TENANT_ID
    # PlatformAdmin and MRM are platform-wide roles — neither is scoped to a
    # single tenant, matching how their GroupMapping entries have tenantId=None.
    if settings.DEV_USER_ROLE in {"PlatformAdmin", "MRM"}:
        tenant_id = None
    return CurrentUser(
        userId=settings.DEV_USER_ID,
        email=settings.DEV_USER_EMAIL,
        name=settings.DEV_USER_NAME,
        role=settings.DEV_USER_ROLE,
        tenantId=tenant_id,
        resolvedFromGroupId="dev-mode-synthetic",
        accessToken=None,
    )


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> CurrentUser:
    # ── Dev mode: synthetic user, no JWT / DynamoDB involved ────────────────
    if settings.is_dev_auth:
        user = _dev_current_user()
        request.state.current_user = user
        return user

    # ── Prod mode: real Entra ID JWT validation + group resolution ─────────
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
            detail="Token is missing a subject/object identifier.",
        )

    resolved = _group_resolver.resolve(payload.groups)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=NO_GROUP_MAPPING_DETAIL,
        )

    user = CurrentUser(
        userId=payload.user_id,
        email=payload.user_email or "",
        name=payload.name or payload.user_email or payload.user_id,
        role=resolved.role,
        tenantId=resolved.tenantId,
        resolvedFromGroupId=resolved.groupId,
        accessToken=token,
    )
    request.state.current_user = user
    return user


def require_role(*allowed_roles: str):
    """Return a dependency that 403s unless the current user has one of
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

    Used for the rare case (MRM-only endpoints) where even PlatformAdmin
    should not bypass the check — currently unused, kept for completeness.
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
