"""Repository for FeatureView entities (Feature Store preview — see db/models.py)."""
from __future__ import annotations

from typing import List, Optional

from boto3.dynamodb.conditions import Key

from app.db.client import clean_item, get_table, strip_internal
from app.db.models import FeatureView, Keys


class FeatureViewRepository:
    def __init__(self) -> None:
        self.table = get_table()

    def _item(self, fv: FeatureView) -> dict:
        return {
            "entityType": "FeatureView",
            **Keys.feature_view(fv.featureViewId),
            **Keys.feature_view_gsi(fv.tenantId, fv.createdAt, fv.featureViewId),
            **fv.model_dump(),
        }

    def create(self, fv: FeatureView) -> FeatureView:
        self.table.put_item(
            Item=clean_item(self._item(fv)),
            ConditionExpression="attribute_not_exists(PK)",
        )
        return fv

    def get(self, feature_view_id: str) -> Optional[FeatureView]:
        resp = self.table.get_item(Key=Keys.feature_view(feature_view_id))
        item = strip_internal(resp.get("Item"))
        return FeatureView(**item) if item else None

    def update(self, fv: FeatureView) -> FeatureView:
        self.table.put_item(
            Item=clean_item(self._item(fv)),
            ConditionExpression="attribute_exists(PK)",
        )
        return fv

    def list_by_tenant(self, tenant_id: str) -> List[FeatureView]:
        resp = self.table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"FV_TENANT#{tenant_id}"),
            ScanIndexForward=False,
        )
        return [FeatureView(**strip_internal(i)) for i in resp.get("Items", [])]

    def list_all(self) -> List[FeatureView]:
        resp = self.table.scan(
            FilterExpression="entityType = :t",
            ExpressionAttributeValues={":t": "FeatureView"},
        )
        return [FeatureView(**strip_internal(i)) for i in resp.get("Items", [])]
