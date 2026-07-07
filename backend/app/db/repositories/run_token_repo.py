"""Repository for RunToken entities (machine identity for training runs).

Stores only the SHA-256 hash of the token. Items auto-expire via the
DynamoDB TTL attribute set to ``expiresAt``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.db.client import clean_item, get_table, strip_internal
from app.db.models import Keys, RunToken


def _iso_to_epoch(iso_ts: str) -> int:
    cleaned = iso_ts.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


class RunTokenRepository:
    def __init__(self) -> None:
        self.table = get_table()

    def create(self, record: RunToken) -> RunToken:
        item = {
            "entityType": "RunToken",
            **Keys.run_token(record.tokenHash),
            "ttl": _iso_to_epoch(record.expiresAt),
            **record.model_dump(),
        }
        self.table.put_item(Item=clean_item(item))
        return record

    def get_by_hash(self, token_hash: str) -> Optional[RunToken]:
        resp = self.table.get_item(Key=Keys.run_token(token_hash))
        item = strip_internal(resp.get("Item"))
        return RunToken(**item) if item else None
