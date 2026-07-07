"""Dataplane client factory: single-account or cross-account, one call site.

``dataplane_client(service, tenant_id)`` is how the backend talks to
resources that live in the dataplane account (EMR Serverless applications,
per-job token secrets):

- ``DATAPLANE_RUNTIME_ROLE_ARN`` unset (local dev / single-account MVP):
  returns the ordinary shared client — behavior identical to before the
  account split existed.
- Set (control-plane/dataplane split): assumes the dataplane's runtime role
  with a ``tenantId`` SESSION TAG. The dataplane role's ABAC policy scopes
  tenant-taggable resources to that same tenantId, so a tenancy bug in this
  codebase cannot reach another tenant's tagged resources. Credentials AND
  the resulting clients are cached per tenant and rotated before expiry.

KMS and S3 deliberately do NOT go through here: their cross-account access
is granted by resource policies (key policy / bucket policy) to the backend
task role directly, so those calls keep using the backend's own credentials
with full ARNs.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional, Tuple

from app.config import settings
from app.db.client import make_boto3_client

# Refresh assumed credentials this many seconds before they expire.
_REFRESH_MARGIN_SECONDS = 300
_SESSION_DURATION_SECONDS = 3600

# One lock guards the cache dict + the per-tenant lock registry; the STS
# network call happens under a PER-TENANT lock so refreshes for different
# tenants don't serialize behind one another.
_registry_lock = threading.Lock()
_tenant_locks: Dict[str, threading.Lock] = {}
# tenant_id -> (expires_epoch, credentials dict)
_creds_cache: Dict[str, Tuple[float, Dict[str, str]]] = {}


def _tenant_lock(tenant_id: str) -> threading.Lock:
    with _registry_lock:
        lock = _tenant_locks.get(tenant_id)
        if lock is None:
            lock = threading.Lock()
            _tenant_locks[tenant_id] = lock
        return lock


def _fresh(entry: Optional[Tuple[float, Dict[str, str]]]) -> bool:
    return entry is not None and time.time() < entry[0] - _REFRESH_MARGIN_SECONDS


def _assumed_credentials(tenant_id: str) -> Tuple[float, Dict[str, str]]:
    """Return ``(expiry_epoch, credentials)`` for the dataplane runtime role
    assumed as ``tenant_id``. Cached per tenant; the epoch lets callers key a
    client cache so it rotates with the credentials."""
    entry = _creds_cache.get(tenant_id)
    if _fresh(entry):
        return entry
    with _tenant_lock(tenant_id):  # only this tenant's refresh serializes
        entry = _creds_cache.get(tenant_id)
        if _fresh(entry):
            return entry
        sts = make_boto3_client("sts", settings.STS_ENDPOINT_URL)
        resp = sts.assume_role(
            RoleArn=settings.DATAPLANE_RUNTIME_ROLE_ARN,
            RoleSessionName=f"tmt-{tenant_id}"[:64],
            DurationSeconds=_SESSION_DURATION_SECONDS,
            Tags=[{"Key": "tenantId", "Value": tenant_id}],
        )
        c = resp["Credentials"]
        entry = (
            c["Expiration"].timestamp(),
            {
                "aws_access_key_id": c["AccessKeyId"],
                "aws_secret_access_key": c["SecretAccessKey"],
                "aws_session_token": c["SessionToken"],
            },
        )
        with _registry_lock:
            # Store this tenant's fresh creds and evict any other tenants'
            # long-expired entries so the cache can't grow without bound.
            _creds_cache[tenant_id] = entry
            cutoff = time.time()
            stale = [t for t, e in _creds_cache.items() if e[0] <= cutoff and t != tenant_id]
            for t in stale:
                _creds_cache.pop(t, None)
        return entry


def dataplane_client(
    service: str, tenant_id: str, endpoint_url: Optional[str] = None
):
    """Return a boto3 client for a dataplane-account service, scoped to
    ``tenant_id`` via ABAC session tags when the account split is enabled.

    In split mode the client is cached per (service, tenant, credential
    epoch, endpoint): reused while the credentials are valid and rebuilt
    automatically when they rotate — a single GET /jobs polling many jobs
    no longer constructs a fresh client per job."""
    if not settings.DATAPLANE_RUNTIME_ROLE_ARN:
        return make_boto3_client(service, endpoint_url)
    expiry, creds = _assumed_credentials(tenant_id)
    return make_boto3_client(
        service,
        endpoint_url,
        credentials=creds,
        cache_key=f"dp:{service}:{tenant_id}:{int(expiry)}:{endpoint_url}",
    )
