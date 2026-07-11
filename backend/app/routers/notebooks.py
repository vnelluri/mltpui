"""Launch and list personal EMR Studio / SageMaker Studio notebook sessions."""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.models import CurrentUser
from app.db.models import NotebookSession, SessionType, utcnow_iso
from app.db.repositories.notebook_repo import NotebookRepository
from app.dependencies import get_current_user, require_role
from app.middleware.tenant_scope import enforce_tenant_access
from app.services.audit_service import audit_service
from app.services.notebook_service import notebook_service

router = APIRouter(prefix="/notebooks", tags=["notebooks"])

_repo = NotebookRepository()


class NotebookLaunchRequest(BaseModel):
    sessionType: str
    tenantId: str
    # Launch in collaborative mode for a business use case (from a model
    # registry row): everyone launching against the same use case shares one
    # workspace instead of getting isolated personal sessions.
    usecaseId: Optional[str] = None


@router.post("/launch", response_model=NotebookSession, status_code=status.HTTP_201_CREATED)
async def launch_notebook(
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
        body.sessionType, body.tenantId, user.userId, usecase_id=body.usecaseId
    )
    session = NotebookSession(
        sessionId=str(uuid.uuid4()),
        userId=user.userId,
        tenantId=body.tenantId,
        sessionType=body.sessionType,
        usecaseId=body.usecaseId,
        presignedUrl=url,
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
async def list_sessions(user: CurrentUser = Depends(get_current_user)) -> Dict[str, Any]:
    items = _repo.list_by_user(user.userId)
    return {"items": items, "total": len(items), "page": 1, "pageSize": len(items) or 1}
