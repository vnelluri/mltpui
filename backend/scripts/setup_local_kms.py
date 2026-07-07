#!/usr/bin/env python
"""Create a LocalStack KMS key + alias and a Secrets Manager placeholder.

Run once before ``create_tables.py`` in local dev (``dev.sh`` / the
``dynamo-init`` compose service do this automatically). Idempotent: skips
key creation if the alias already exists. Writes the key ARN to
``.env.local`` for manual reference (and prints it either way).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

ENDPOINT_URL = os.environ.get("KMS_ENDPOINT_URL") or "http://localhost:4566"
SECRETS_ENDPOINT_URL = os.environ.get("SECRETS_MANAGER_ENDPOINT_URL") or ENDPOINT_URL
REGION = os.environ.get("AWS_REGION", "us-east-1")
ALIAS_NAME = "alias/ml-platform-snowflake"
PLACEHOLDER_SECRET_NAME = "ml-platform/job-tokens/_setup-check"

# backend/.env.local — NOT the repo root: inside the container, only ./backend
# is mounted at /app, so the repo root doesn't exist as a path there.
ENV_LOCAL_PATH = Path(__file__).resolve().parent.parent / ".env.local"


def _boto_kwargs(endpoint_url: str) -> dict:
    return {
        "region_name": REGION,
        "endpoint_url": endpoint_url,
        "aws_access_key_id": os.environ.get("AWS_ACCESS_KEY_ID") or "test",
        "aws_secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY") or "test",
    }


def ensure_kms_key() -> str:
    client = boto3.client("kms", **_boto_kwargs(ENDPOINT_URL))
    try:
        resp = client.describe_key(KeyId=ALIAS_NAME)
        key_id = resp["KeyMetadata"]["KeyId"]
        print(f"✔ KMS alias '{ALIAS_NAME}' already exists (key id {key_id}).")
        return resp["KeyMetadata"]["Arn"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"NotFoundException", "InvalidArnException"}:
            raise

    created = client.create_key(
        Description="ML Platform — encrypts per-user Snowflake OAuth tokens at rest.",
        KeyUsage="ENCRYPT_DECRYPT",
    )
    key_id = created["KeyMetadata"]["KeyId"]
    key_arn = created["KeyMetadata"]["Arn"]
    client.create_alias(AliasName=ALIAS_NAME, TargetKeyId=key_id)
    print(f"✔ Created KMS key {key_id} with alias '{ALIAS_NAME}'.")
    return key_arn


def ensure_secrets_manager_ready() -> None:
    client = boto3.client("secretsmanager", **_boto_kwargs(SECRETS_ENDPOINT_URL))
    try:
        client.create_secret(
            Name=PLACEHOLDER_SECRET_NAME,
            SecretString="{}",
            Description="Setup check — proves Secrets Manager is reachable for job token transit.",
        )
        print(f"✔ Secrets Manager reachable (created check secret '{PLACEHOLDER_SECRET_NAME}').")
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceExistsException":
            print("✔ Secrets Manager reachable (check secret already present).")
        else:
            raise


def write_env_local(key_arn: str) -> None:
    """Best-effort: write the key ARN to backend/.env.local for manual reference.

    Never fatal — the app doesn't require this file (it defaults to the
    'alias/ml-platform-snowflake' alias when KMS_SNOWFLAKE_KEY_ARN is unset),
    so a read-only filesystem or permission issue here should not fail setup.
    """
    line = f"KMS_SNOWFLAKE_KEY_ARN={key_arn}\n"
    try:
        existing = ENV_LOCAL_PATH.read_text() if ENV_LOCAL_PATH.exists() else ""
        if "KMS_SNOWFLAKE_KEY_ARN=" in existing:
            return
        with ENV_LOCAL_PATH.open("a") as f:
            f.write(line)
        print(f"✔ Wrote KMS_SNOWFLAKE_KEY_ARN to {ENV_LOCAL_PATH}")
    except OSError as exc:
        print(f"(skipped writing {ENV_LOCAL_PATH}: {exc}) — key ARN: {key_arn}")


def main() -> None:
    print(f"LocalStack endpoint: {ENDPOINT_URL}")
    key_arn = ensure_kms_key()
    ensure_secrets_manager_ready()
    write_env_local(key_arn)
    print(f"\nKey ARN: {key_arn}")
    print(
        "Note: the app auto-encrypts against 'alias/ml-platform-snowflake' when "
        "KMS_SNOWFLAKE_KEY_ARN is unset, so this ARN is informational for local dev."
    )


if __name__ == "__main__":
    main()
