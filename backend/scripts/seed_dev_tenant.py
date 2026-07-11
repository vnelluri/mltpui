#!/usr/bin/env python
"""Seed ONLY the dev user's tenant — the bare minimum for exercising the
model/review flow on an otherwise empty platform (SEED_DEMO_DATA=false).

Creates the tenant record (with mock dataplane fields, matching what the
provisioning service fills in locally) and the shared artifacts bucket.
No jobs, experiments, models, or reviews are seeded. Idempotent.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from botocore.exceptions import ClientError  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.client import make_boto3_client  # noqa: E402
from app.db.repositories.tenant_repo import TenantRepository  # noqa: E402
from seed_demo_data import _demo_tenant, _ensure_bucket  # noqa: E402


def main() -> None:
    tenant_id = os.environ.get("DEV_USER_TENANT_ID", "tenant-risk-analytics").strip()
    name = tenant_id.removeprefix("tenant-").replace("-", " ").title() or tenant_id
    tenant = _demo_tenant(tenant_id, name, 2000, ["pytorch", "tensorflow", "sklearn", "xgboost"])
    try:
        TenantRepository().create(tenant)
        print(f"* Created tenant '{tenant_id}' ({name}).")
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            print(f"* Tenant '{tenant_id}' already exists — left as is.")
        else:
            raise

    _ensure_bucket(make_boto3_client("s3", settings.S3_ENDPOINT_URL))
    print(f"* Artifacts bucket ready: s3://{settings.S3_ARTIFACTS_BUCKET}")


if __name__ == "__main__":
    main()
