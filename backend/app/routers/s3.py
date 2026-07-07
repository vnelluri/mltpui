"""Browse the shared artifacts S3 bucket, scoped to the caller's tenant prefix.

Every tenant's data lives under a `{tenantId}/` prefix in the single shared
`S3_ARTIFACTS_BUCKET` (created by the provisioning pipeline, or by the mock
tenant-provisioning service in local dev). This is
real S3 traffic (no mock mode) — against LocalStack in local dev, or real S3
in prod — since LocalStack already emulates S3 faithfully.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.models import CurrentUser
from app.config import settings
from app.db.client import make_boto3_client
from app.dependencies import get_current_user

router = APIRouter(prefix="/s3", tags=["s3"])


def _client():
    return make_boto3_client("s3", settings.S3_ENDPOINT_URL)


@router.get("/browse")
async def browse(
    prefix: str = "",
    user: CurrentUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """List folders (common prefixes) and files under ``prefix``.

    Non-PlatformAdmin users are confined to their own tenant's prefix
    (``{tenantId}/``): a blank prefix is forced to that tenant's root, and
    any attempt to browse outside it is rejected — this is enforced here at
    the API layer, not just hidden in the UI.
    """
    if not user.is_platform_admin:
        if not user.tenantId:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="No tenant assigned."
            )
        tenant_root = f"{user.tenantId}/"
        if not prefix:
            prefix = tenant_root
        elif not prefix.startswith(tenant_root):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You may only browse your own tenant's S3 prefix.",
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
