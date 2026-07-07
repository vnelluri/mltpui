"""Repository for GroupMapping entities (source of truth for role/tenant)."""
from __future__ import annotations

from typing import List, Optional, Tuple

from boto3.dynamodb.conditions import Key

from app.db.client import clean_item, get_table, strip_internal
from app.db.models import GroupMapping, Keys


class GroupMappingRepository:
    def __init__(self) -> None:
        self.table = get_table()

    def _item(self, gm: GroupMapping) -> dict:
        return {
            "entityType": "GroupMapping",
            **Keys.group_mapping(gm.groupId),
            **Keys.group_mapping_gsi(gm.tenantId, gm.role, gm.groupId),
            **gm.model_dump(),
        }

    def create(self, gm: GroupMapping) -> GroupMapping:
        self.table.put_item(
            Item=clean_item(self._item(gm)),
            ConditionExpression="attribute_not_exists(PK)",
        )
        return gm

    def upsert(self, gm: GroupMapping) -> GroupMapping:
        self.table.put_item(Item=clean_item(self._item(gm)))
        return gm

    def get(self, group_id: str) -> Optional[GroupMapping]:
        resp = self.table.get_item(Key=Keys.group_mapping(group_id))
        item = strip_internal(resp.get("Item"))
        return GroupMapping(**item) if item else None

    def list_all(
        self, limit: int = 50, start_key: Optional[dict] = None
    ) -> Tuple[List[GroupMapping], Optional[dict]]:
        kwargs = {
            "FilterExpression": "begins_with(PK, :p) AND SK = PK",
            "ExpressionAttributeValues": {":p": "GROUPMAPPING#"},
            "Limit": limit,
        }
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        resp = self.table.scan(**kwargs)
        items = [GroupMapping(**strip_internal(i)) for i in resp.get("Items", [])]
        return items, resp.get("LastEvaluatedKey")

    def list_by_tenant(self, tenant_id: Optional[str]) -> List[GroupMapping]:
        resp = self.table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(
                f"GM_TENANT#{tenant_id or 'PLATFORM'}"
            ),
        )
        return [GroupMapping(**strip_internal(i)) for i in resp.get("Items", [])]

    def list_by_role(self, role: str) -> List[GroupMapping]:
        resp = self.table.query(
            IndexName="GSI2",
            KeyConditionExpression=Key("GSI2PK").eq(f"GM_ROLE#{role}"),
        )
        return [GroupMapping(**strip_internal(i)) for i in resp.get("Items", [])]

    def update(self, gm: GroupMapping) -> GroupMapping:
        self.table.put_item(
            Item=clean_item(self._item(gm)),
            ConditionExpression="attribute_exists(PK)",
        )
        return gm

    def delete(self, group_id: str) -> bool:
        resp = self.table.delete_item(
            Key=Keys.group_mapping(group_id),
            ReturnValues="ALL_OLD",
        )
        return resp.get("Attributes") is not None

    def resolve_groups(self, group_ids: List[str]) -> List[GroupMapping]:
        """Return every GroupMapping matching any of the given group OIDs."""
        results: List[GroupMapping] = []
        for gid in group_ids:
            gm = self.get(gid)
            if gm is not None:
                results.append(gm)
        return results
