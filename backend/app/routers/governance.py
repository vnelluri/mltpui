"""MRM governance review workflow."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.models import CurrentUser
from app.db.models import GovernanceReview, ReviewDecision, utcnow_iso
from app.db.repositories.audit_repo import AuditRepository
from app.db.repositories.experiment_repo import ExperimentRepository
from app.db.repositories.governance_repo import GovernanceRepository
from app.db.repositories.model_repo import ModelRepository
from app.dependencies import get_current_user, require_role
from app.middleware.tenant_scope import enforce_tenant_access
from app.services.audit_service import audit_service
from app.services.model_card_service import build_governance_export

router = APIRouter(prefix="/governance", tags=["governance"])

_repo = GovernanceRepository()
_model_repo = ModelRepository()
_exp_repo = ExperimentRepository()
_audit_repo = AuditRepository()


class ReviewCreateRequest(BaseModel):
    modelId: str
    modelName: str
    modelVersion: int


class ReviewDecisionRequest(BaseModel):
    decision: str
    comments: Optional[str] = None
    conditions: Optional[str] = None
    expiresAt: Optional[str] = None


@router.get("/reviews")
async def list_reviews(
    page: int = 1, pageSize: int = 20, user: CurrentUser = Depends(require_role("MRM"))
) -> Dict[str, Any]:
    if user.sees_all_tenants:
        items = _repo.list_all()
    else:
        items = _repo.list_by_tenant(user.tenantId)
    total = len(items)
    start = (page - 1) * pageSize
    return {
        "items": items[start : start + pageSize],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }


@router.post("/reviews", response_model=GovernanceReview, status_code=status.HTTP_201_CREATED)
async def create_review(
    body: ReviewCreateRequest,
    request: Request,
    user: CurrentUser = Depends(require_role("MRM")),
) -> GovernanceReview:
    mv = _model_repo.get_by_model_id(body.modelId, body.modelVersion) or _model_repo.get_version(
        body.modelName, body.modelVersion
    )
    if mv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model version not found.")
    review = GovernanceReview(
        reviewId=str(uuid.uuid4()),
        modelId=mv.modelId,
        tenantId=mv.tenantId,
        modelName=mv.name,
        modelVersion=mv.version,
        reviewedBy=user.userId,
        decision=ReviewDecision.PENDING.value,
    )
    _repo.create(review)
    audit_service.record(
        user=user,
        action="governance.review_create",
        resource_type="GovernanceReview",
        resource_id=review.reviewId,
        tenant_id=mv.tenantId,
        request=request,
    )
    return review


@router.get("/reviews/{review_id}", response_model=GovernanceReview)
async def get_review(
    review_id: str, user: CurrentUser = Depends(require_role("MRM"))
) -> GovernanceReview:
    review = _repo.get(review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")
    enforce_tenant_access(user, review.tenantId)
    return review


@router.put("/reviews/{review_id}", response_model=GovernanceReview)
async def submit_decision(
    review_id: str,
    body: ReviewDecisionRequest,
    request: Request,
    user: CurrentUser = Depends(require_role("MRM")),
) -> GovernanceReview:
    review = _repo.get(review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")
    enforce_tenant_access(user, review.tenantId)
    review.decision = body.decision
    review.comments = body.comments
    review.conditions = body.conditions
    review.expiresAt = body.expiresAt
    review.reviewedBy = user.userId
    review.reviewedAt = utcnow_iso()
    updated = _repo.update(review)
    audit_service.record(
        user=user,
        action="governance.review_decision",
        resource_type="GovernanceReview",
        resource_id=review_id,
        tenant_id=review.tenantId,
        details={"decision": body.decision},
        request=request,
    )
    return updated


@router.get("/export/{model_id}/{ver}")
async def export_governance_package(
    model_id: str, ver: int, user: CurrentUser = Depends(require_role("MRM"))
) -> Dict[str, Any]:
    mv = _model_repo.get_by_model_id(model_id, ver)
    if mv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model version not found.")
    enforce_tenant_access(user, mv.tenantId)
    run = _exp_repo.get_run_by_id(mv.tenantId, mv.runId) if mv.runId else None
    reviews = _repo.list_by_model(mv.modelId)
    audit_events, _ = _audit_repo.list_by_tenant(mv.tenantId, limit=200)
    audit_dicts = [e.model_dump() for e in audit_events if e.resourceId in {mv.modelId, f"{mv.name}/{mv.version}"}]
    return build_governance_export(mv, run, reviews, audit_dicts)
