"""Authentication endpoints: resolved identity, dev token debugging, Snowflake token exchange."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth.models import CurrentUser
from app.config import settings
from app.dependencies import get_current_user
from app.routers.snowflake import connect_snowflake

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=CurrentUser)
async def get_me(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """The resolved principal, with memberships enriched with tenant display
    names (group names only carry tenant IDs; the Tenant table is where a
    meaningful name is assigned). Done here rather than on every request —
    only the UI needs names."""
    from app.db.repositories.tenant_repo import TenantRepository

    repo = TenantRepository()
    names: dict = {}
    for m in user.memberships:
        if m.tenantId and m.tenantId not in names:
            tenant = repo.get(m.tenantId)
            names[m.tenantId] = tenant.name if tenant else None
        if m.tenantId:
            m.tenantName = names[m.tenantId]
    return user


@router.get("/token-info")
async def token_info(request: Request) -> Dict[str, Any]:
    """Decoded JWT claims for local debugging. Disabled outside dev mode."""
    if not settings.is_dev_auth:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="/auth/token-info is only available when AUTH_MODE=dev.",
        )
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:]
        from app.auth.cognito import TokenValidationError, decode_unverified

        try:
            payload = decode_unverified(token)
            return {"source": "bearer_token", "claims": payload.raw, "groups": payload.groups}
        except TokenValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not decode token: {exc}",
            ) from exc

    return {
        "source": "dev_synthetic_user",
        "claims": {
            "sub": settings.DEV_USER_ID,
            "email": settings.DEV_USER_EMAIL,
            "given_name": settings.DEV_USER_NAME,
        },
        "groups": [],
        "note": (
            "No bearer token was supplied. This reflects the synthetic "
            "AUTH_MODE=dev user; DEV_USER_ROLE/DEV_USER_TENANT_ID (and "
            "DEV_USER_MEMBERSHIPS) drive role/tenant resolution directly, "
            "bypassing the group-name convention."
        ),
    }


@router.get("/snowflake-token")
async def get_snowflake_token(
    user: CurrentUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """Exchange the current user's bearer token for a Snowflake OAuth token.

    The raw token is never returned — only the resolved username and expiry.
    """
    cache = connect_snowflake(user)
    return {"snowflakeUsername": cache.snowflakeUsername, "expiresAt": cache.expiresAt}
