"""Browse the shared artifacts S3 bucket, scoped to the caller's tenant prefix.

Every tenant's data lives under a `{tenantId}/` prefix in the single shared
`S3_ARTIFACTS_BUCKET` (created by the provisioning pipeline, or by the mock
tenant-provisioning service in local dev). This is
real S3 traffic (no mock mode) — against LocalStack in local dev, or real S3
in prod — since LocalStack already emulates S3 faithfully.
"""
from __future__ import annotations

import posixpath
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from app.auth.models import CurrentUser
from app.config import settings
from app.db.client import make_boto3_client
from app.db.models import Role
from app.dependencies import get_current_user
from app.services.audit_service import audit_service

router = APIRouter(prefix="/s3", tags=["s3"])

# Uploads go through the backend (no presigned URLs, so no bucket CORS
# needed); cap the size to keep request bodies sane.
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def _client():
    return make_boto3_client("s3", settings.S3_ENDPOINT_URL)


def _root_prefix_for(user: CurrentUser) -> str:
    """The root prefix a non-PlatformAdmin caller is confined to.

    MRM is a platform-wide role (its membership never carries a tenant), so
    it gets the shared ``mrm/`` area instead of a tenant prefix.
    """
    if user.is_mrm:
        return "mrm/"
    if not user.tenantId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No tenant assigned."
        )
    return f"{user.tenantId}/"


@router.get("/browse")
async def browse(
    prefix: str = "",
    user: CurrentUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """List folders (common prefixes) and files under ``prefix``.

    Non-PlatformAdmin users are confined to their own root prefix — the
    tenant's (``{tenantId}/``), or the platform-level ``mrm/`` area for MRM
    (which never has a tenant): a blank prefix is forced to that root, and
    any attempt to browse outside it is rejected — this is enforced here at
    the API layer, not just hidden in the UI.
    """
    if not user.is_platform_admin:
        root = _root_prefix_for(user)
        if not prefix:
            prefix = root
        elif not prefix.startswith(root):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You may only browse your own S3 prefix.",
            )

    if prefix and not prefix.endswith("/"):
        prefix = prefix + "/"

    bucket = settings.S3_ARTIFACTS_BUCKET
    client = _client()
    resp = client.list_objects_v2(Bucket=bucket, Prefix=prefix, Delimiter="/")

    folders = [cp["Prefix"] for cp in resp.get("CommonPrefixes", [])]
    files = [
        {
            "key": obj["Key"],
            "size": obj["Size"],
            "lastModified": obj["LastModified"].isoformat(),
        }
        for obj in resp.get("Contents", [])
        # Skip the ".keep" placeholder written at tenant provisioning time and
        # the prefix "folder" marker object itself (S3 has no real folders).
        if not obj["Key"].endswith("/.keep") and obj["Key"] != prefix
    ]

    return {"bucket": bucket, "prefix": prefix, "folders": folders, "files": files}


@router.post("/upload")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    prefix: Optional[str] = Form(None),
    user: CurrentUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """Upload a file into the caller's own prefix.

    Data Scientists and MRM only. The destination defaults to the caller's
    personal directory — ``{tenantId}/users/{userId}/`` for tenant-scoped
    roles, ``mrm/{userId}/`` for MRM (a platform-wide role with no tenant).
    A caller-supplied prefix is accepted but confined to that root —
    enforced here, not just in the UI, same as ``/browse``.
    """
    if user.role not in (Role.DATA_SCIENTIST.value, Role.MRM.value):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Data Scientists and MRM may upload files.",
        )

    root = _root_prefix_for(user)
    default_dir = f"{root}{user.userId}/" if user.is_mrm else f"{root}users/{user.userId}/"
    dest = prefix or default_dir
    if not dest.endswith("/"):
        dest += "/"
    # Normalize to defeat "../" escapes before the root check.
    if not posixpath.normpath(dest).startswith(root.rstrip("/")) or not dest.startswith(root):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You may only upload into your own S3 prefix.",
        )

    filename = posixpath.basename(file.filename or "")
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing file name."
        )

    body = await file.read()
    if len(body) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds the 100 MB upload limit.",
        )

    key = f"{dest}{filename}"
    bucket = settings.S3_ARTIFACTS_BUCKET
    _client().put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType=file.content_type or "application/octet-stream",
    )

    audit_service.record(
        user=user,
        action="s3.upload",
        resource_type="S3Object",
        resource_id=key,
        tenant_id=user.tenantId,
        details={"bucket": bucket, "size": len(body)},
        request=request,
    )
    return {"bucket": bucket, "key": key, "size": len(body)}
