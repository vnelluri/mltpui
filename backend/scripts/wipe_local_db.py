#!/usr/bin/env python
"""Wipe ALL local data — delete + recreate the DynamoDB table and empty the
artifacts bucket — WITHOUT reseeding, for testing from a clean slate.

(reset_local_db.py is the delete-and-reseed variant.)

Only intended for local development. Pass --yes to skip the confirmation
prompt. The moto server (or LocalStack) must be running.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import os  # noqa: E402
import time  # noqa: E402

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "ml-platform")
DDB_ENDPOINT = os.environ.get("DYNAMODB_ENDPOINT_URL") or "http://localhost:5000"
S3_ENDPOINT = os.environ.get("S3_ENDPOINT_URL") or DDB_ENDPOINT
BUCKET = os.environ.get("S3_ARTIFACTS_BUCKET", "ml-platform-artifacts")
REGION = os.environ.get("AWS_REGION", "us-east-1")
CREDS = {
    "aws_access_key_id": os.environ.get("AWS_ACCESS_KEY_ID") or "test",
    "aws_secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY") or "test",
}


def wipe_table() -> None:
    client = boto3.client("dynamodb", region_name=REGION, endpoint_url=DDB_ENDPOINT, **CREDS)
    try:
        client.delete_table(TableName=TABLE_NAME)
        client.get_waiter("table_not_exists").wait(TableName=TABLE_NAME)
        print(f"* Table '{TABLE_NAME}' deleted.")
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        print(f"* Table '{TABLE_NAME}' did not exist.")
    time.sleep(1)
    import create_tables

    create_tables.main()


def empty_bucket() -> None:
    s3 = boto3.resource("s3", region_name=REGION, endpoint_url=S3_ENDPOINT, **CREDS)
    try:
        bucket = s3.Bucket(BUCKET)
        deleted = 0
        for batch in [list(bucket.objects.all())[i : i + 1000] for i in range(0, 10_000, 1000)]:
            if not batch:
                break
            bucket.delete_objects(Delete={"Objects": [{"Key": o.key} for o in batch]})
            deleted += len(batch)
        print(f"* Emptied s3://{BUCKET} ({deleted} objects).")
    except ClientError as exc:
        if exc.response["Error"]["Code"] in {"404", "NoSuchBucket"}:
            print(f"* Bucket '{BUCKET}' did not exist.")
        else:
            raise


def main() -> None:
    if "--yes" not in sys.argv:
        answer = input(
            f"This will DELETE ALL data in table '{TABLE_NAME}' and empty "
            f"s3://{BUCKET} (no reseed). Continue? [y/N] "
        ).strip().lower()
        if answer != "y":
            print("Aborted. No changes made.")
            return
    wipe_table()
    empty_bucket()
    print("\nLocal data wiped — the platform is empty (no tenants, models, jobs).")
    print("Tip: seeding on startup is controlled by SEED_DEMO_DATA in backend/.env.")


if __name__ == "__main__":
    main()
