"""Snowflake OAuth connect/status/disconnect + read-only query & browsing.

All endpoints operate on the current user's cached Snowflake OAuth token
(never the raw token itself, which is never returned to the client).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.auth.models import CurrentUser
from app.db.models import SnowflakeTokenCache
from app.db.repositories.snowflake_token_repo import SnowflakeTokenRepository
from app.dependencies import get_current_user
from app.services.audit_service import audit_service
from app.services.snowflake_service import (
    KmsCipher,
    SqlValidationError,
    snowflake_service,
    validate_select_only,
    wrap_with_limit,
)

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


def connect_snowflake(user: CurrentUser) -> SnowflakeTokenCache:
    """Exchange the user's Entra token for a Snowflake OAuth token and cache it.

    Shared by ``POST /snowflake/connect`` and ``GET /auth/snowflake-token``.
    """
    entra_token = user.accessToken or "dev-mode-token"
    raw_token, username, expires_at = snowflake_service.exchange_token(
        entra_token, user.email
    )
    cipher = KmsCipher(tenant_id=user.tenantId)
    encrypted = cipher.encrypt(raw_token)
    cache = SnowflakeTokenCache(
        userId=user.userId,
        snowflakeToken=encrypted,
        expiresAt=expires_at,
        tenantId=user.tenantId,
        snowflakeUsername=username,
    )
    return _token_repo.put(cache)


def _get_valid_token(user: CurrentUser) -> str:
    cache = _token_repo.get(user.userId)
    if cache is None or _is_expired(cache.expiresAt):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not connected to Snowflake. Connect first via POST /snowflake/connect.",
        )
    cipher = KmsCipher(tenant_id=user.tenantId)
    return cipher.decrypt(cache.snowflakeToken)


class SnowflakeStatusResponse(BaseModel):
    connected: bool
    snowflakeUsername: Optional[str] = None
    expiresAt: Optional[str] = None


class SnowflakeQueryRequest(BaseModel):
    sql: str
    database: str
    schema_: str = Field(alias="schema")
    warehouse: str
    limit: int = 1000

    model_config = {"populate_by_name": True}


@router.get("/status", response_model=SnowflakeStatusResponse)
async def snowflake_status(
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
async def snowflake_connect(
    request: Request, user: CurrentUser = Depends(get_current_user)
) -> SnowflakeStatusResponse:
    cache = connect_snowflake(user)
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


@router.post("/disconnect")
async def snowflake_disconnect(
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
async def snowflake_query(
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
async def list_databases(user: CurrentUser = Depends(get_current_user)) -> List[str]:
    token = _get_valid_token(user)
    return snowflake_service.list_databases(token)


@router.get("/databases/{db}/schemas")
async def list_schemas(db: str, user: CurrentUser = Depends(get_current_user)) -> List[str]:
    token = _get_valid_token(user)
    try:
        return snowflake_service.list_schemas(token, db)
    except SqlValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/databases/{db}/schemas/{schema}/tables")
async def list_tables(
    db: str, schema: str, user: CurrentUser = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    token = _get_valid_token(user)
    try:
        return snowflake_service.list_tables(token, db, schema)
    except SqlValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/databases/{db}/schemas/{schema}/tables/{table}/preview")
async def preview_table(
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
