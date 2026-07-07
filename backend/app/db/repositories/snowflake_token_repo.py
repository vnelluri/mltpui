"""Repository for the SnowflakeTokenCache entity.

Stores per-user Snowflake OAuth tokens encrypted with KMS. The plaintext
token is never handled here; only the already-encrypted (base64) ciphertext
is persisted. A DynamoDB TTL attribute (``ttl``) is set to ``expiresAt`` so
stale tokens auto-expire.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.db.client import clean_item, get_table, strip_internal
from app.db.models import Keys, SnowflakeTokenCache


def _iso_to_epoch(iso_ts: str) -> int:
    """Convert an ISO-8601 timestamp to a Unix epoch (for DynamoDB TTL)."""
    cleaned = iso_ts.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


class SnowflakeTokenRepository:
    def __init__(self) -> None:
        self.table = get_table()

    def put(self, cache: SnowflakeTokenCache) -> SnowflakeTokenCache:
        item = {
            "entityType": "SnowflakeTokenCache",
            **Keys.snowflake_token(cache.userId),
            "ttl": _iso_to_epoch(cache.expiresAt),
            **cache.model_dump(),
        }
        self.table.put_item(Item=clean_item(item))
        return cache

    def get(self, user_id: str) -> Optional[SnowflakeTokenCache]:
        resp = self.table.get_item(Key=Keys.snowflake_token(user_id))
        item = strip_internal(resp.get("Item"))
        if not item:
            return None
        return SnowflakeTokenCache(**item)

    def delete(self, user_id: str) -> bool:
        resp = self.table.delete_item(
            Key=Keys.snowflake_token(user_id),
            ReturnValues="ALL_OLD",
        )
        return resp.get("Attributes") is not None
