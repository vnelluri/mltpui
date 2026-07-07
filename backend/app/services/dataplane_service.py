"""Dataplane client factory: single-account or cross-account, one call site.

``dataplane_client(service, tenant_id)`` is how the backend talks to
resources that live in the dataplane account (EMR Serverless applications,
per-job token secrets):

- ``DATAPLANE_RUNTIME_ROLE_ARN`` unset (local dev / single-account MVP):
  returns the ordinary shared client — behavior identical to before the
  account split existed.
- Set (control-plane/dataplane split): assumes the dataplane's runtime role
  with a ``tenantId`` SESSION TAG. The dataplane role's ABAC policy only
  matches resources tagged with that same tenantId, so even a tenancy bug in
  this codebase cannot reach another tenant's application. Credentials are
  cached per tenant and refreshed before expiry.

KMS and S3 deliberately do NOT go through here: their cross-account access
is granted by resource policies (key policy / bucket policy) to the backend
task role directly, so those calls keep using the backend's own credentials
with full ARNs.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Tuple

import boto3

from app.config import settings
from app.db.client import _BOTO_CONFIG, make_boto3_client

# Refresh assumed credentials this many seconds before they expire.
_REFRESH_MARGIN_SECONDS = 300
_SESSION_DURATION_SECONDS = 3600

_lock = threading.Lock()
# tenant_id -> (expires_epoch, credentials dict)
_creds_cache: Dict[str, Tuple[float, Dict[str, str]]] = {}


def _assumed_credentials(tenant_id: str) -> Dict[str, str]:
    now = time.time()
    cached = _creds_cache.get(tenant_id)
    if cached and now < cached[0] - _REFRESH_MARGIN_SECONDS:
        return cached[1]
    with _lock:
        cached = _creds_cache.get(tenant_id)
        if cached and time.time() < cached[0] - _REFRESH_MARGIN_SECONDS:
            return cached[1]
        sts = make_boto3_client("sts", settings.STS_ENDPOINT_URL)
        resp = sts.assume_role(
            RoleArn=settings.DATAPLANE_RUNTIME_ROLE_ARN,
            RoleSessionName=f"tmt-{tenant_id}"[:64],
            DurationSeconds=_SESSION_DURATION_SECONDS,
            Tags=[{"Key": "tenantId", "Value": tenant_id}],
        )
        c = resp["Credentials"]
        creds = {
            "aws_access_key_id": c["AccessKeyId"],
            "aws_secret_access_key": c["SecretAccessKey"],
            "aws_session_token": c["SessionToken"],
        }
        _creds_cache[tenant_id] = (c["Expiration"].timestamp(), creds)
        return creds


def dataplane_client(
    service: str, tenant_id: str, endpoint_url: Optional[str] = None
):
    """Return a boto3 client for a dataplane-account service, scoped to
    ``tenant_id`` via ABAC session tags when the account split is enabled."""
    if not settings.DATAPLANE_RUNTIME_ROLE_ARN:
        return make_boto3_client(service, endpoint_url)
    kwargs: Dict[str, Any] = {
        "region_name": settings.AWS_REGION,
        "config": _BOTO_CONFIG,
        **_assumed_credentials(tenant_id),
    }
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client(service, **kwargs)
