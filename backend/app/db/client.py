"""DynamoDB single-table client and boto3 helpers.

Provides a shared boto3 resource/table and value-conversion helpers so the
rest of the application deals with plain Python types (int/float/str/dict)
rather than DynamoDB's ``Decimal`` representation.

All boto3 clients are built with :func:`make_boto3_client` /
:func:`make_boto3_resource` which transparently point at LocalStack (or any
custom endpoint) and inject dummy credentials when an endpoint override is
configured — LocalStack does not validate real AWS credentials.
"""
from __future__ import annotations

import threading
from decimal import Decimal
from typing import Any, Dict, Optional

import boto3
from botocore.config import Config as BotoConfig

from app.config import settings

_BOTO_CONFIG = BotoConfig(
    retries={"max_attempts": 3, "mode": "standard"},
    connect_timeout=5,
    read_timeout=30,
)

_lock = threading.Lock()
_resource_cache: Dict[str, Any] = {}
_client_cache: Dict[str, Any] = {}


def _credentials(endpoint_url: Optional[str]) -> Dict[str, str]:
    """Return credential kwargs.

    When an endpoint override is set (LocalStack) and no real credentials
    were provided, inject dummy credentials so boto3 does not fail on missing
    credentials.
    """
    creds: Dict[str, str] = {}
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        creds["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
        creds["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    elif endpoint_url:
        creds["aws_access_key_id"] = "test"
        creds["aws_secret_access_key"] = "test"
    return creds


def make_boto3_client(
    service: str,
    endpoint_url: Optional[str] = None,
    credentials: Optional[Dict[str, str]] = None,
    cache_key: Optional[str] = None,
):
    """Create (and cache) a boto3 client for ``service``.

    ``credentials`` overrides the default credential resolution (used for
    cross-account assumed-role sessions); when supplied, callers must also
    pass a ``cache_key`` that changes whenever the credentials rotate, so a
    stale-credential client is never reused.
    """
    key = cache_key or f"{service}:{endpoint_url}"
    client = _client_cache.get(key)
    if client is not None:
        return client
    with _lock:
        client = _client_cache.get(key)
        if client is None:
            kwargs: Dict[str, Any] = {
                "region_name": settings.AWS_REGION,
                "config": _BOTO_CONFIG,
                **(credentials if credentials is not None else _credentials(endpoint_url)),
            }
            if endpoint_url:
                kwargs["endpoint_url"] = endpoint_url
            client = boto3.client(service, **kwargs)
            _client_cache[key] = client
    return client


def make_boto3_resource(service: str, endpoint_url: Optional[str] = None):
    """Create (and cache) a boto3 resource for ``service``."""
    key = f"{service}:{endpoint_url}"
    resource = _resource_cache.get(key)
    if resource is not None:
        return resource
    with _lock:
        resource = _resource_cache.get(key)
        if resource is None:
            kwargs: Dict[str, Any] = {
                "region_name": settings.AWS_REGION,
                "config": _BOTO_CONFIG,
                **_credentials(endpoint_url),
            }
            if endpoint_url:
                kwargs["endpoint_url"] = endpoint_url
            resource = boto3.resource(service, **kwargs)
            _resource_cache[key] = resource
    return resource


def get_dynamodb_resource():
    """Return the shared DynamoDB resource."""
    return make_boto3_resource("dynamodb", settings.DYNAMODB_ENDPOINT_URL)


def get_table():
    """Return the single application DynamoDB table."""
    return get_dynamodb_resource().Table(settings.DYNAMODB_TABLE_NAME)


# ── Value conversion helpers ────────────────────────────────────────────────
def to_dynamo(value: Any) -> Any:
    """Recursively convert a Python value into a DynamoDB-safe value.

    - ``float`` → ``Decimal`` (via ``str`` to avoid binary-float noise)
    - ``None`` values inside dicts are dropped (DynamoDB dislikes nulls in
      condition-heavy items; explicit nulls are rarely needed here)
    - empty strings are preserved (DynamoDB supports them)
    """
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return {k: to_dynamo(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple, set)):
        return [to_dynamo(v) for v in value]
    return value


def from_dynamo(value: Any) -> Any:
    """Recursively convert DynamoDB values back into plain Python types."""
    if isinstance(value, Decimal):
        # Represent integral decimals as int, otherwise float.
        if value % 1 == 0:
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {k: from_dynamo(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [from_dynamo(v) for v in value]
    if isinstance(value, set):
        return [from_dynamo(v) for v in value]
    return value


def clean_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare a dict for DynamoDB: drop ``None`` and convert floats."""
    return {k: to_dynamo(v) for k, v in item.items() if v is not None}


# Internal single-table attributes that never appear on domain models.
INTERNAL_KEYS = {
    "PK",
    "SK",
    "GSI1PK",
    "GSI1SK",
    "GSI2PK",
    "GSI2SK",
    "entityType",
    "ttl",
}


def strip_internal(item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Remove single-table key/marker attributes and convert Decimals."""
    if item is None:
        return None
    clean = {k: v for k, v in item.items() if k not in INTERNAL_KEYS}
    return from_dynamo(clean)
