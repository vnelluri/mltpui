#!/usr/bin/env python
"""Delete and recreate the local DynamoDB table, then reseed demo data.

Only intended for LocalStack / local development — prompts for confirmation
before deleting anything.
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


def main() -> None:
    answer = input(
        "This will delete all local data. Continue? [y/N] "
    ).strip().lower()
    if answer != "y":
        print("Aborted. No changes made.")
        return

    client = _client()
    try:
        client.delete_table(TableName=TABLE_NAME)
        print(f"Deleting table '{TABLE_NAME}' ...")
        waiter = client.get_waiter("table_not_exists")
        waiter.wait(TableName=TABLE_NAME)
        print(f"✔ Table '{TABLE_NAME}' deleted.")
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"Table '{TABLE_NAME}' did not exist — nothing to delete.")
        else:
            raise

    time.sleep(1)

    import create_tables
    import seed_demo_data

    create_tables.main()
    seed_demo_data.main()
    print("\n✔ Local database reset complete.")


if __name__ == "__main__":
    main()
