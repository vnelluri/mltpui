#!/usr/bin/env python
"""Create the single DynamoDB table (with all GSIs) used by the platform.

Idempotent: skips creation if the table already exists. Works against
LocalStack (``DYNAMODB_ENDPOINT_URL``, defaults to ``http://localhost:4566``
when unset) and against real AWS (leave ``DYNAMODB_ENDPOINT_URL`` unset there
too, but set real AWS credentials/region).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "ml-platform")
ENDPOINT_URL = os.environ.get("DYNAMODB_ENDPOINT_URL") or "http://localhost:4566"
REGION = os.environ.get("AWS_REGION", "us-east-1")


def _client():
    kwargs = {"region_name": REGION}
    if ENDPOINT_URL:
        kwargs["endpoint_url"] = ENDPOINT_URL
        kwargs["aws_access_key_id"] = os.environ.get("AWS_ACCESS_KEY_ID") or "test"
        kwargs["aws_secret_access_key"] = os.environ.get("AWS_SECRET_ACCESS_KEY") or "test"
    return boto3.client("dynamodb", **kwargs)


def table_exists(client) -> bool:
    try:
        client.describe_table(TableName=TABLE_NAME)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise


def create_table(client) -> None:
    client.create_table(
        TableName=TABLE_NAME,
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
            {"AttributeName": "GSI2PK", "AttributeType": "S"},
            {"AttributeName": "GSI2SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "GSI2",
                "KeySchema": [
                    {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    waiter = client.get_waiter("table_exists")
    waiter.wait(TableName=TABLE_NAME)

    client.update_time_to_live(
        TableName=TABLE_NAME,
        TimeToLiveSpecification={"AttributeName": "ttl", "Enabled": True},
    )


def main() -> None:
    client = _client()
    print(f"Target table: {TABLE_NAME}  (endpoint: {ENDPOINT_URL or 'real AWS'})")

    if table_exists(client):
        print(f"✔ Table '{TABLE_NAME}' already exists — skipping creation.")
    else:
        print(f"Creating table '{TABLE_NAME}' with GSI1, GSI2 ...")
        create_table(client)
        print(f"✔ Table '{TABLE_NAME}' created.")

    desc = client.describe_table(TableName=TABLE_NAME)["Table"]
    gsi_names = [g["IndexName"] for g in desc.get("GlobalSecondaryIndexes", [])]
    print(f"Table ARN: {desc['TableArn']}")
    print(f"GSIs: {', '.join(gsi_names) if gsi_names else '(none)'}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"✘ create_tables.py failed: {exc}", file=sys.stderr)
        # Give LocalStack a moment in case it was still booting; caller can retry.
        time.sleep(1)
        sys.exit(1)
