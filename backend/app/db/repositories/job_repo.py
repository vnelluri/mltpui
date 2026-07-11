"""Repository for TrainingJob entities."""
from __future__ import annotations

from typing import List, Optional, Tuple

from boto3.dynamodb.conditions import Key

from app.db.client import clean_item, get_table, strip_internal
from app.db.models import Keys, TrainingJob


class JobRepository:
    def __init__(self) -> None:
        self.table = get_table()

    def _item(self, job: TrainingJob) -> dict:
        return {
            "entityType": "TrainingJob",
            **Keys.job(job.jobId),
            **Keys.job_gsi(job.tenantId, job.status, job.userId, job.createdAt),
            **job.model_dump(),
        }

    def create(self, job: TrainingJob) -> TrainingJob:
        self.table.put_item(
            Item=clean_item(self._item(job)),
            ConditionExpression="attribute_not_exists(PK)",
        )
        return job

    def next_job_number(self) -> int:
        """Next sequential number for human-friendly job ids (job-0001, …).

        Job ids are the GLOBAL primary key (JOB#<id>, no tenant component),
        so the sequence is platform-wide. Backed by an atomic counter item —
        DynamoDB's ADD is race-free, so concurrent submissions can never be
        handed the same number.
        """
        resp = self.table.update_item(
            Key={"PK": "COUNTER#job", "SK": "COUNTER#job"},
            UpdateExpression="ADD #n :one",
            ExpressionAttributeNames={"#n": "n"},
            ExpressionAttributeValues={":one": 1},
            ReturnValues="UPDATED_NEW",
        )
        return int(resp["Attributes"]["n"])

    def get(self, job_id: str) -> Optional[TrainingJob]:
        resp = self.table.get_item(Key=Keys.job(job_id))
        item = strip_internal(resp.get("Item"))
        return TrainingJob(**item) if item else None

    def update(self, job: TrainingJob) -> TrainingJob:
        self.table.put_item(
            Item=clean_item(self._item(job)),
            ConditionExpression="attribute_exists(PK)",
        )
        return job

    def list_by_tenant(
        self, tenant_id: str, limit: int = 100, start_key: Optional[dict] = None
    ) -> Tuple[List[TrainingJob], Optional[dict]]:
        kwargs = {
            "IndexName": "GSI1",
            "KeyConditionExpression": Key("GSI1PK").eq(f"JOB_TENANT#{tenant_id}"),
            "Limit": limit,
            "ScanIndexForward": False,
        }
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        resp = self.table.query(**kwargs)
        items = [TrainingJob(**strip_internal(i)) for i in resp.get("Items", [])]
        return items, resp.get("LastEvaluatedKey")

    def list_by_tenant_status(
        self, tenant_id: str, status: str, limit: int = 100
    ) -> List[TrainingJob]:
        resp = self.table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"JOB_TENANT#{tenant_id}")
            & Key("GSI1SK").begins_with(f"STATUS#{status}#"),
            Limit=limit,
            ScanIndexForward=False,
        )
        return [TrainingJob(**strip_internal(i)) for i in resp.get("Items", [])]

    def list_by_user(self, user_id: str, limit: int = 100) -> List[TrainingJob]:
        resp = self.table.query(
            IndexName="GSI2",
            KeyConditionExpression=Key("GSI2PK").eq(f"JOB_USER#{user_id}"),
            Limit=limit,
            ScanIndexForward=False,
        )
        return [TrainingJob(**strip_internal(i)) for i in resp.get("Items", [])]

    def list_all(
        self, limit: int = 100, start_key: Optional[dict] = None
    ) -> Tuple[List[TrainingJob], Optional[dict]]:
        kwargs = {
            "FilterExpression": "begins_with(PK, :p) AND SK = PK",
            "ExpressionAttributeValues": {":p": "JOB#"},
            "Limit": limit,
        }
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        resp = self.table.scan(**kwargs)
        items = [TrainingJob(**strip_internal(i)) for i in resp.get("Items", [])]
        return items, resp.get("LastEvaluatedKey")
