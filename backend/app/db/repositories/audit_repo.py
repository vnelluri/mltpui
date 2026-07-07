"""Repository for AuditEvent entities."""
from __future__ import annotations

from typing import List, Optional, Tuple

from boto3.dynamodb.conditions import Key

from app.db.client import clean_item, get_table, strip_internal
from app.db.models import AuditEvent, Keys


class AuditRepository:
    def __init__(self) -> None:
        self.table = get_table()

    def create(self, event: AuditEvent) -> AuditEvent:
        item = {
            "entityType": "AuditEvent",
            **Keys.audit(event.eventId),
            **Keys.audit_gsi(
                event.tenantId, event.userId, event.timestamp, event.eventId
            ),
            **event.model_dump(),
        }
        self.table.put_item(Item=clean_item(item))
        return event

    def get(self, event_id: str) -> Optional[AuditEvent]:
        resp = self.table.get_item(Key=Keys.audit(event_id))
        item = strip_internal(resp.get("Item"))
        return AuditEvent(**item) if item else None

    def list_by_tenant(
        self,
        tenant_id: Optional[str],
        limit: int = 100,
        start_key: Optional[dict] = None,
    ) -> Tuple[List[AuditEvent], Optional[dict]]:
        kwargs = {
            "IndexName": "GSI1",
            "KeyConditionExpression": Key("GSI1PK").eq(
                f"AUDIT_TENANT#{tenant_id or 'PLATFORM'}"
            ),
            "Limit": limit,
            "ScanIndexForward": False,
        }
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        resp = self.table.query(**kwargs)
        items = [AuditEvent(**strip_internal(i)) for i in resp.get("Items", [])]
        return items, resp.get("LastEvaluatedKey")

    def list_by_user(
        self, user_id: str, limit: int = 100, start_key: Optional[dict] = None
    ) -> Tuple[List[AuditEvent], Optional[dict]]:
        kwargs = {
            "IndexName": "GSI2",
            "KeyConditionExpression": Key("GSI2PK").eq(f"AUDIT_USER#{user_id}"),
            "Limit": limit,
            "ScanIndexForward": False,
        }
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        resp = self.table.query(**kwargs)
        items = [AuditEvent(**strip_internal(i)) for i in resp.get("Items", [])]
        return items, resp.get("LastEvaluatedKey")

    def list_all(
        self, limit: int = 200, start_key: Optional[dict] = None
    ) -> Tuple[List[AuditEvent], Optional[dict]]:
        kwargs = {
            "FilterExpression": "entityType = :t",
            "ExpressionAttributeValues": {":t": "AuditEvent"},
            "Limit": limit,
        }
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        resp = self.table.scan(**kwargs)
        items = [AuditEvent(**strip_internal(i)) for i in resp.get("Items", [])]
        return items, resp.get("LastEvaluatedKey")
