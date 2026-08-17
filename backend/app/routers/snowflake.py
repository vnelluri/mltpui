"""Snowflake OAuth connect/status/disconnect + read-only query & browsing.

Connecting is an Entra authorization-code flow (Snowflake validates the
Entra-issued tokens via External OAuth): POST /connect hands the SPA an
authorize URL, Entra redirects back to GET /oauth/callback, and the tokens
are cached KMS-encrypted. All other endpoints operate on the cached token —
transparently refreshed from the stored Entra refresh token when expired —
and the raw token is never returned to the client.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.auth.models import CurrentUser
from app.config import settings
from app.db.models import SnowflakeTokenCache
from app.db.repositories.snowflake_token_repo import SnowflakeTokenRepository
from app.dependencies import get_current_user
from app.services.audit_service import audit_service
from app.services.snowflake_service import (
    KmsCipher,
    SqlValidationError,
    make_oauth_state,
    snowflake_service,
    validate_select_only,
    verify_oauth_state,
    wrap_with_limit,
)

logger = logging.getLogger("ml_platform.snowflake")

router = APIRouter(prefix="/snowflake", tags=["snowflake"])

_token_repo = SnowflakeTokenRepository()


def _is_expired(expires_at: str) -> bool:
    cleaned = (expires_at or "").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt <= datetime.now(timezone.utc)


def _store_tokens(
    user_id: str,
    tenant_id: Optional[str],
    username: str,
    access_token: str,
    expires_at: str,
    refresh_token: Optional[str] = None,
    refresh_expires_at: Optional[str] = None,
) -> SnowflakeTokenCache:
    """KMS-encrypt and cache the user's Snowflake (Entra-issued) tokens."""
    cipher = KmsCipher(tenant_id=tenant_id)
    cache = SnowflakeTokenCache(
        userId=user_id,
        snowflakeToken=cipher.encrypt(access_token),
        snowflakeRefreshToken=(
            cipher.encrypt(refresh_token) if refresh_token else None
        ),
        expiresAt=expires_at,
        refreshExpiresAt=refresh_expires_at,
        tenantId=tenant_id,
        snowflakeUsername=username,
    )
    return _token_repo.put(cache)


def connect_snowflake_mock(user: CurrentUser) -> SnowflakeTokenCache:
    """Mock-mode connect: fabricate and cache a token (local dev).

    Shared by ``POST /snowflake/connect`` and ``GET /auth/snowflake-token``.
    """
    raw_token, username, expires_at = snowflake_service.mock_connect(user.email)
    return _store_tokens(user.userId, user.tenantId, username, raw_token, expires_at)


def ensure_valid_cache(user: CurrentUser) -> SnowflakeTokenCache:
    """Return a cache row with a valid access token, refreshing if possible.

    Raises 400 when the user has never connected (or the refresh failed) —
    the SPA then offers POST /snowflake/connect.
    """
    cache = _token_repo.get(user.userId)
    if cache is not None and not _is_expired(cache.expiresAt):
        return cache
    if (
        cache is not None
        and cache.snowflakeRefreshToken
        and not settings.SNOWFLAKE_MOCK_MODE
    ):
        cipher = KmsCipher(tenant_id=user.tenantId)
        old_refresh = cipher.decrypt(cache.snowflakeRefreshToken)
        try:
            bundle = snowflake_service.refresh_access_token(old_refresh)
        except Exception:
            # Transient failure or revoked refresh token — keep the row (its
            # TTL reaps it) and fall through to "reconnect".
            logger.warning("Snowflake token refresh failed for user %s", user.userId)
        else:
            return _store_tokens(
                user.userId,
                user.tenantId,
                cache.snowflakeUsername,
                bundle["access_token"],
                bundle["expires_at"],
                bundle.get("refresh_token") or old_refresh,
                bundle.get("refresh_expires_at") or cache.refreshExpiresAt,
            )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Not connected to Snowflake. Connect first via POST /snowflake/connect.",
    )


def _get_valid_token(user: CurrentUser) -> str:
    cache = ensure_valid_cache(user)
    cipher = KmsCipher(tenant_id=user.tenantId)
    return cipher.decrypt(cache.snowflakeToken)


class SnowflakeStatusResponse(BaseModel):
    connected: bool
    snowflakeUsername: Optional[str] = None
    expiresAt: Optional[str] = None
    # Real mode only: set when connecting requires the user's consent at
    # Entra — the SPA redirects the browser here and the tokens come back
    # via GET /snowflake/oauth/callback.
    authorizeUrl: Optional[str] = None


class SnowflakeQueryRequest(BaseModel):
    sql: str
    database: str
    schema_: str = Field(alias="schema")
    warehouse: str
    limit: int = 1000

    model_config = {"populate_by_name": True}


@router.get("/status", response_model=SnowflakeStatusResponse)
def snowflake_status(
    user: CurrentUser = Depends(get_current_user),
) -> SnowflakeStatusResponse:
    cache = _token_repo.get(user.userId)
    if cache is None:
        return SnowflakeStatusResponse(connected=False)
    expired = _is_expired(cache.expiresAt)
    return SnowflakeStatusResponse(
        connected=not expired,
        snowflakeUsername=cache.snowflakeUsername,
        expiresAt=cache.expiresAt,
    )


@router.post("/connect", response_model=SnowflakeStatusResponse)
def snowflake_connect(
    request: Request, user: CurrentUser = Depends(get_current_user)
) -> SnowflakeStatusResponse:
    if settings.SNOWFLAKE_MOCK_MODE:
        cache = connect_snowflake_mock(user)
        audit_service.record(
            user=user,
            action="snowflake.connect",
            resource_type="SnowflakeTokenCache",
            resource_id=user.userId,
            request=request,
        )
        return SnowflakeStatusResponse(
            connected=True,
            snowflakeUsername=cache.snowflakeUsername,
            expiresAt=cache.expiresAt,
        )
    # Real mode: connecting needs the user's consent at Entra — hand the SPA
    # the authorize URL; tokens arrive via GET /oauth/callback.
    state = make_oauth_state(user.userId, user.email, user.tenantId, user.role)
    return SnowflakeStatusResponse(
        connected=False,
        authorizeUrl=snowflake_service.build_authorize_url(state),
    )


@router.get("/oauth/callback", include_in_schema=False)
def snowflake_oauth_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
) -> RedirectResponse:
    """Entra's redirect target.

    Arrives WITHOUT our Authorization header — the user identity comes from
    the HMAC-signed ``state`` minted by POST /connect, never from anything
    Entra sends. Redirects back to the SPA either way.
    """
    front = (settings.frontend_base_url or "").rstrip("/")

    def bounce(failed: bool = False) -> RedirectResponse:
        suffix = "?error=snowflake_connect_failed" if failed else "?connected=1"
        return RedirectResponse(url=f"{front}/snowflake{suffix}")

    claims = verify_oauth_state(state or "")
    if error or not code or not claims:
        logger.warning("Snowflake OAuth callback rejected (error=%s)", error)
        return bounce(failed=True)
    try:
        bundle = snowflake_service.redeem_auth_code(code)
    except Exception:
        logger.exception("Snowflake OAuth code redemption failed")
        return bounce(failed=True)
    username = snowflake_service._derive_username(bundle.get("email") or claims["e"])
    _store_tokens(
        claims["u"],
        claims.get("t"),
        username,
        bundle["access_token"],
        bundle["expires_at"],
        bundle.get("refresh_token"),
        bundle.get("refresh_expires_at"),
    )
    audit_service.record(
        user=CurrentUser(
            userId=claims["u"],
            email=claims["e"],
            name=claims["e"],
            role=claims["r"],
            tenantId=claims.get("t"),
        ),
        action="snowflake.connect",
        resource_type="SnowflakeTokenCache",
        resource_id=claims["u"],
        request=request,
    )
    return bounce()


@router.post("/disconnect")
def snowflake_disconnect(
    request: Request, user: CurrentUser = Depends(get_current_user)
) -> dict:
    _token_repo.delete(user.userId)
    audit_service.record(
        user=user,
        action="snowflake.disconnect",
        resource_type="SnowflakeTokenCache",
        resource_id=user.userId,
        request=request,
    )
    return {"detail": "Disconnected from Snowflake."}


@router.post("/query")
def snowflake_query(
    body: SnowflakeQueryRequest, user: CurrentUser = Depends(get_current_user)
) -> Dict[str, Any]:
    try:
        safe_sql = validate_select_only(body.sql)
    except SqlValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    limit = max(1, min(int(body.limit), 1000))
    wrapped = wrap_with_limit(safe_sql, limit)
    token = _get_valid_token(user)
    result = snowflake_service.execute_query(
        token, wrapped, body.database, body.schema_, body.warehouse, limit
    )
    return {
        "columns": result.columns,
        "rows": result.rows,
        "rowCount": result.rowCount,
        "queryId": result.queryId,
    }


@router.get("/databases")
def list_databases(user: CurrentUser = Depends(get_current_user)) -> List[str]:
    token = _get_valid_token(user)
    return snowflake_service.list_databases(token)


@router.get("/databases/{db}/schemas")
def list_schemas(db: str, user: CurrentUser = Depends(get_current_user)) -> List[str]:
    token = _get_valid_token(user)
    try:
        return snowflake_service.list_schemas(token, db)
    except SqlValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/databases/{db}/schemas/{schema}/tables")
def list_tables(
    db: str, schema: str, user: CurrentUser = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    token = _get_valid_token(user)
    try:
        return snowflake_service.list_tables(token, db, schema)
    except SqlValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/databases/{db}/schemas/{schema}/tables/{table}/preview")
def preview_table(
    db: str, schema: str, table: str, user: CurrentUser = Depends(get_current_user)
) -> Dict[str, Any]:
    token = _get_valid_token(user)
    try:
        result = snowflake_service.get_table_preview(token, db, schema, table, rows=10)
    except SqlValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "columns": result.columns,
        "rows": result.rows,
        "rowCount": result.rowCount,
        "queryId": result.queryId,
    }
