"""Repository for ModelVersion entities."""
from __future__ import annotations

from typing import List, Optional

from boto3.dynamodb.conditions import Key

from app.db.client import clean_item, get_table, strip_internal
from app.db.models import Keys, ModelVersion, pad_version


class ModelRepository:
    def __init__(self) -> None:
        self.table = get_table()

    def _item(self, mv: ModelVersion) -> dict:
        return {
            "entityType": "ModelVersion",
            **Keys.model_version(mv.tenantId, mv.name, mv.version),
            **Keys.model_version_gsi(
                mv.tenantId, mv.stage, mv.name, mv.version, mv.modelId
            ),
            **mv.model_dump(),
        }

    def create(self, mv: ModelVersion) -> ModelVersion:
        self.table.put_item(
            Item=clean_item(self._item(mv)),
            ConditionExpression="attribute_not_exists(SK)",
        )
        return mv

    def update(self, mv: ModelVersion) -> ModelVersion:
        self.table.put_item(
            Item=clean_item(self._item(mv)),
            ConditionExpression="attribute_exists(SK)",
        )
        return mv

    def get_version(
        self, tenant_id: str, name: str, version: int
    ) -> Optional[ModelVersion]:
        resp = self.table.get_item(Key=Keys.model_version(tenant_id, name, version))
        item = strip_internal(resp.get("Item"))
        return ModelVersion(**item) if item else None

    def get_by_model_id(self, model_id: str, version: int) -> Optional[ModelVersion]:
        resp = self.table.query(
            IndexName="GSI2",
            KeyConditionExpression=Key("GSI2PK").eq(f"MODELID#{model_id}")
            & Key("GSI2SK").eq(f"VERSION#{pad_version(version)}"),
        )
        items = resp.get("Items", [])
        if not items:
            return None
        return ModelVersion(**strip_internal(items[0]))

    def list_versions(self, tenant_id: str, name: str) -> List[ModelVersion]:
        resp = self.table.query(
            KeyConditionExpression=Key("PK").eq(f"MODEL#{tenant_id}#{name}")
            & Key("SK").begins_with("VERSION#"),
        )
        return [ModelVersion(**strip_internal(i)) for i in resp.get("Items", [])]

    def latest_version_number(self, tenant_id: str, name: str) -> int:
        versions = self.list_versions(tenant_id, name)
        if not versions:
            return 0
        return max(v.version for v in versions)

    def list_by_tenant(self, tenant_id: str) -> List[ModelVersion]:
        resp = self.table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"MODEL_TENANT#{tenant_id}"),
        )
        return [ModelVersion(**strip_internal(i)) for i in resp.get("Items", [])]

    def list_all(self) -> List[ModelVersion]:
        resp = self.table.scan(
            FilterExpression="entityType = :t",
            ExpressionAttributeValues={":t": "ModelVersion"},
        )
        return [ModelVersion(**strip_internal(i)) for i in resp.get("Items", [])]
