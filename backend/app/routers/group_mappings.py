"""PlatformAdmin CRUD for Entra group -> (role, tenant) mappings."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.models import CurrentUser
from app.db.models import GroupMapping
from app.db.repositories.group_mapping_repo import GroupMappingRepository
from app.dependencies import require_role
from app.services.audit_service import audit_service

router = APIRouter(prefix="/group-mappings", tags=["group-mappings"])

_repo = GroupMappingRepository()


class GroupMappingCreateRequest(BaseModel):
    groupId: str
    role: str
    tenantId: Optional[str] = None
    description: Optional[str] = None


class GroupMappingUpdateRequest(BaseModel):
    role: Optional[str] = None
    tenantId: Optional[str] = None
    description: Optional[str] = None


@router.post("", response_model=GroupMapping, status_code=status.HTTP_201_CREATED)
async def create_group_mapping(
    body: GroupMappingCreateRequest,
    request: Request,
    user: CurrentUser = Depends(require_role("PlatformAdmin")),
) -> GroupMapping:
    if _repo.get(body.groupId) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A mapping for this group ID already exists.",
        )
    gm = GroupMapping(
        groupId=body.groupId,
        role=body.role,
        tenantId=body.tenantId,
        description=body.description,
        createdBy=user.userId,
    )
    _repo.create(gm)
    audit_service.record(
        user=user,
        action="group_mapping.create",
        resource_type="GroupMapping",
        resource_id=gm.groupId,
        tenant_id=gm.tenantId,
        request=request,
    )
    return gm


@router.get("")
async def list_group_mappings(
    page: int = 1, pageSize: int = 20, user: CurrentUser = Depends(require_role("PlatformAdmin"))
) -> Dict[str, Any]:
    items, _ = _repo.list_all(limit=500)
    total = len(items)
    start = (page - 1) * pageSize
    return {
        "items": items[start : start + pageSize],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }


@router.get("/{group_id}", response_model=GroupMapping)
async def get_group_mapping(
    group_id: str, user: CurrentUser = Depends(require_role("PlatformAdmin"))
) -> GroupMapping:
    gm = _repo.get(group_id)
    if gm is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group mapping not found.")
    return gm


@router.put("/{group_id}", response_model=GroupMapping)
async def update_group_mapping(
    group_id: str,
    body: GroupMappingUpdateRequest,
    request: Request,
    user: CurrentUser = Depends(require_role("PlatformAdmin")),
) -> GroupMapping:
    gm = _repo.get(group_id)
    if gm is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group mapping not found.")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(gm, field, value)
    updated = _repo.update(gm)
    audit_service.record(
        user=user,
        action="group_mapping.update",
        resource_type="GroupMapping",
        resource_id=group_id,
        tenant_id=gm.tenantId,
        request=request,
    )
    return updated


@router.delete("/{group_id}")
async def delete_group_mapping(
    group_id: str, request: Request, user: CurrentUser = Depends(require_role("PlatformAdmin"))
) -> Dict[str, str]:
    gm = _repo.get(group_id)
    if gm is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group mapping not found.")
    _repo.delete(group_id)
    audit_service.record(
        user=user,
        action="group_mapping.delete",
        resource_type="GroupMapping",
        resource_id=group_id,
        tenant_id=gm.tenantId,
        request=request,
    )
    return {"detail": "Group mapping deleted. Affected users lose access on next login."}
