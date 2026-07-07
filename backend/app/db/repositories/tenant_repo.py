"""Repository for Tenant entities."""
from __future__ import annotations

from typing import List, Optional, Tuple

from boto3.dynamodb.conditions import Key

from app.db.client import clean_item, get_table, strip_internal
from app.db.models import Keys, Tenant, TenantStatus


class TenantRepository:
    def __init__(self) -> None:
        self.table = get_table()

    def create(self, tenant: Tenant) -> Tenant:
        item = {
            "entityType": "Tenant",
            **Keys.tenant(tenant.tenantId),
            **Keys.tenant_gsi(tenant.status, tenant.tenantId),
            **tenant.model_dump(),
        }
        self.table.put_item(
            Item=clean_item(item),
            ConditionExpression="attribute_not_exists(PK)",
        )
        return tenant

    def get(self, tenant_id: str) -> Optional[Tenant]:
        resp = self.table.get_item(Key=Keys.tenant(tenant_id))
        item = strip_internal(resp.get("Item"))
        return Tenant(**item) if item else None

    def list_all(
        self, limit: int = 50, start_key: Optional[dict] = None
    ) -> Tuple[List[Tenant], Optional[dict]]:
        # Scan constrained to tenant meta items (SK == PK) by a filter.
        kwargs = {"Limit": limit}
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        resp = self.table.scan(
            FilterExpression="begins_with(PK, :p) AND SK = PK",
            ExpressionAttributeValues={":p": "TENANT#"},
            **kwargs,
        )
        items = [Tenant(**strip_internal(i)) for i in resp.get("Items", [])]
        return items, resp.get("LastEvaluatedKey")

    def list_by_status(self, status: str) -> List[Tenant]:
        resp = self.table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"TENANT_STATUS#{status}"),
        )
        return [Tenant(**strip_internal(i)) for i in resp.get("Items", [])]

    def update(self, tenant: Tenant) -> Tenant:
        item = {
            "entityType": "Tenant",
            **Keys.tenant(tenant.tenantId),
            **Keys.tenant_gsi(tenant.status, tenant.tenantId),
            **tenant.model_dump(),
        }
        self.table.put_item(
            Item=clean_item(item),
            ConditionExpression="attribute_exists(PK)",
        )
        return tenant

    def set_status(self, tenant_id: str, status: str) -> Optional[Tenant]:
        tenant = self.get(tenant_id)
        if tenant is None:
            return None
        tenant.status = status
        return self.update(tenant)
