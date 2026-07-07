"""Repository for GovernanceReview entities."""
from __future__ import annotations

from typing import List, Optional

from boto3.dynamodb.conditions import Key

from app.db.client import clean_item, get_table, strip_internal
from app.db.models import GovernanceReview, Keys


class GovernanceRepository:
    def __init__(self) -> None:
        self.table = get_table()

    def _item(self, review: GovernanceReview) -> dict:
        return {
            "entityType": "GovernanceReview",
            **Keys.review(review.reviewId),
            **Keys.review_gsi(
                review.modelId, review.tenantId, review.createdAt, review.reviewId
            ),
            **review.model_dump(),
        }

    def create(self, review: GovernanceReview) -> GovernanceReview:
        self.table.put_item(
            Item=clean_item(self._item(review)),
            ConditionExpression="attribute_not_exists(PK)",
        )
        return review

    def get(self, review_id: str) -> Optional[GovernanceReview]:
        resp = self.table.get_item(Key=Keys.review(review_id))
        item = strip_internal(resp.get("Item"))
        return GovernanceReview(**item) if item else None

    def update(self, review: GovernanceReview) -> GovernanceReview:
        self.table.put_item(
            Item=clean_item(self._item(review)),
            ConditionExpression="attribute_exists(PK)",
        )
        return review

    def list_by_model(self, model_id: str) -> List[GovernanceReview]:
        resp = self.table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"REVIEW_MODEL#{model_id}"),
            ScanIndexForward=False,
        )
        return [GovernanceReview(**strip_internal(i)) for i in resp.get("Items", [])]

    def list_by_tenant(self, tenant_id: str) -> List[GovernanceReview]:
        resp = self.table.query(
            IndexName="GSI2",
            KeyConditionExpression=Key("GSI2PK").eq(f"REVIEW_TENANT#{tenant_id}"),
            ScanIndexForward=False,
        )
        return [GovernanceReview(**strip_internal(i)) for i in resp.get("Items", [])]

    def list_all(self) -> List[GovernanceReview]:
        resp = self.table.scan(
            FilterExpression="entityType = :t",
            ExpressionAttributeValues={":t": "GovernanceReview"},
        )
        return [GovernanceReview(**strip_internal(i)) for i in resp.get("Items", [])]

    def has_approved_review(self, model_id: str) -> bool:
        for review in self.list_by_model(model_id):
            if review.decision == "approved":
                return True
        return False
