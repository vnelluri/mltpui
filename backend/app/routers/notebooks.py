"""Launch and list personal EMR Studio / SageMaker Studio notebook sessions."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.models import CurrentUser
from app.config import settings
from app.db.models import NotebookSession, SessionType, utcnow_iso
from app.db.repositories.notebook_repo import NotebookRepository
from app.dependencies import get_current_user, require_role
from app.middleware.tenant_scope import enforce_tenant_access
from app.services.audit_service import audit_service
from app.services.job_service import job_service
from app.services.notebook_service import notebook_service

logger = logging.getLogger("ml_platform.notebook")

router = APIRouter(prefix="/notebooks", tags=["notebooks"])

_repo = NotebookRepository()


def mint_snowflake_session_secret(
    user: CurrentUser, tenant_id: str
) -> Optional[str]:
    """Best-effort: mint the user's Snowflake token and stash it as a
    capability secret for this notebook session (Tier 1 of
    docs/NOTEBOOK_SNOWFLAKE_OIDC.md).

    Returns the random secret name — the capability, surfaced ONCE in the
    launch response — or None when the user never connected Snowflake or
    minting failed. A notebook without Snowflake is fine; the launch never
    fails on this.
    """
    from app.routers.snowflake import ensure_valid_cache
    from app.services.snowflake_service import KmsCipher

    try:
        # Refreshes from the stored Entra refresh token when expired;
        # raises 400 when the user never connected.
        cache = ensure_valid_cache(user)
    except HTTPException:
        return None
    try:
        token = KmsCipher(tenant_id=user.tenantId).decrypt(cache.snowflakeToken)
        return job_service.store_snowflake_session_secret(
            tenant_id,
            {
                "account": settings.SNOWFLAKE_ACCOUNT or "",
                "access_token": token,
                "expiresAt": cache.expiresAt,
                "username": cache.snowflakeUsername,
            },
        )
    except Exception:
        logger.warning(
            "Could not mint Snowflake session secret for user %s — notebook "
            "launches without Snowflake.",
            user.userId,
            exc_info=True,
        )
        return None


class NotebookLaunchRequest(BaseModel):
    sessionType: str
    tenantId: str
    # Launch in collaborative mode for a business use case (from a model
    # registry row): everyone launching against the same use case shares one
    # workspace instead of getting isolated personal sessions.
    usecaseId: Optional[str] = None


@router.post("/launch", response_model=NotebookSession, status_code=status.HTTP_201_CREATED)
def launch_notebook(
    body: NotebookLaunchRequest,
    request: Request,
    user: CurrentUser = Depends(require_role("TenantAdmin", "DataScientist")),
) -> NotebookSession:
    if body.sessionType not in {SessionType.EMR_STUDIO.value, SessionType.SAGEMAKER_STUDIO.value}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sessionType must be 'emr_studio' or 'sagemaker_studio'.",
        )
    enforce_tenant_access(user, body.tenantId)

    url, expires_at = notebook_service.launch(
        body.sessionType, body.tenantId, user.userId, user.role, usecase_id=body.usecaseId
    )
    session = NotebookSession(
        sessionId=str(uuid.uuid4()),
        userId=user.userId,
        tenantId=body.tenantId,
        sessionType=body.sessionType,
        usecaseId=body.usecaseId,
        presignedUrl=url,
        snowflakeSecretName=mint_snowflake_session_secret(user, body.tenantId),
        urlExpiresAt=expires_at,
        status="active",
    )
    _repo.create(session)
    audit_service.record(
        user=user,
        action="notebook.launch",
        resource_type="NotebookSession",
        resource_id=session.sessionId,
        tenant_id=body.tenantId,
        details={"sessionType": body.sessionType, "usecaseId": body.usecaseId},
        request=request,
    )
    return session


@router.get("/sessions")
def list_sessions(user: CurrentUser = Depends(get_current_user)) -> Dict[str, Any]:
    items = _repo.list_by_user(user.userId)
    return {"items": items, "total": len(items), "page": 1, "pageSize": len(items) or 1}
