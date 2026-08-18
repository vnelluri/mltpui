"""Repository for NotebookSession entities."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from boto3.dynamodb.conditions import Attr, Key

from app.db.client import clean_item, get_table, strip_internal
from app.db.models import Keys, NotebookSession


class NotebookRepository:
    def __init__(self) -> None:
        self.table = get_table()

    def create(self, session: NotebookSession) -> NotebookSession:
        item = {
            "entityType": "NotebookSession",
            **Keys.notebook(session.sessionId),
            **Keys.notebook_gsi(
                session.userId, session.createdAt, session.sessionId
            ),
            # A presigned URL is a credential — returned once in the launch
            # response, never persisted. The Snowflake secret NAME is
            # persisted: the background refresher must find it to rewrite
            # the secret, and the capability defends against same-tenant
            # KERNELS (which cannot read this table or ListSecrets) — the
            # control-plane DB is already trusted with far more (the
            # KMS-encrypted refresh tokens themselves).
            **session.model_dump(exclude={"presignedUrl"}),
        }
        self.table.put_item(Item=clean_item(item))
        return session

    def get(self, session_id: str) -> Optional[NotebookSession]:
        resp = self.table.get_item(Key=Keys.notebook(session_id))
        item = strip_internal(resp.get("Item"))
        return NotebookSession(**item) if item else None

    def list_by_user(self, user_id: str) -> List[NotebookSession]:
        resp = self.table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"NB_USER#{user_id}"),
            ScanIndexForward=False,
        )
        return [NotebookSession(**strip_internal(i)) for i in resp.get("Items", [])]

    def list_active(self, max_age_hours: int) -> List[NotebookSession]:
        """Active sessions younger than ``max_age_hours`` — the background
        Snowflake-secret refresher's work list. A filtered scan is fine here:
        sessions are few and the refresher runs on a minutes-scale interval.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        resp = self.table.scan(
            FilterExpression=(
                Attr("entityType").eq("NotebookSession")
                & Attr("status").eq("active")
                & Attr("createdAt").gt(cutoff)
            )
        )
        return [NotebookSession(**strip_internal(i)) for i in resp.get("Items", [])]
