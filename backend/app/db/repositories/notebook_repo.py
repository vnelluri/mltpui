"""Repository for NotebookSession entities."""
from __future__ import annotations

from typing import List, Optional

from boto3.dynamodb.conditions import Key

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
            **session.model_dump(),
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
