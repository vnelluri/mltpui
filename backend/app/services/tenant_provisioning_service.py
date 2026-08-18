"""Tenant dataplane provisioning — direct boto3 calls, no event pipeline.

Tenant creation provisions the per-tenant dataplane resources itself through
``dataplane_client`` (the runtime role assumed with a ``tenantId`` session
tag in the account split; plain backend credentials in single-account mode):

1. **KMS key + alias** ``alias/ml-platform-snowflake-<tenant>`` — Snowflake
   token encryption (matches ``KmsCipher``'s alias convention).
2. **Execution role** ``ml-platform-tenant-<tenant>-exec`` — matches the
   ``…-tenant-*-exec`` PassRole pattern already granted to the backend task
   role; trusted by EMR Serverless + SageMaker; scoped to the tenant's S3
   prefix and KMS key.
3. **EMR Serverless application** — with the interactive endpoint enabled so
   EMR Studio Workspaces can attach (see docs/EMR_STUDIO_LAUNCH.md §3).
4. **S3 prefix marker** in the artifacts bucket (backend's own credentials —
   S3 access is resource-policy based, see dataplane_service).

Every step is **idempotent**: skipped when the tenant record already carries
the resource id, and AlreadyExists races resolve by reading the existing
resource — so a failed provision is safely re-driven via
``POST /tenants/{id}/provision``. Failures set ``provisioningStatus=failed``
with the error recorded on the tenant; job submission stays rejected until
``active``. ``PUT /tenants/{id}/provisioning`` remains as a manual override
for out-of-band-provisioned resources.

``TENANT_PROVISIONING_MOCK_MODE=true`` (local dev): mock resource ids, the
S3 prefix marker, straight to ``active`` — zero AWS accounts.

Dataplane runtime-role permissions this needs (owned by ``tmt-dataplane``),
beyond the job-path ABAC: ``kms:CreateKey/CreateAlias/DescribeKey/
TagResource``, ``iam:CreateRole/GetRole/PutRolePolicy/TagRole`` (orgs with a
permissions boundary typically allow CreateRole only when the boundary is
attached — set ``TENANT_ROLE_PERMISSIONS_BOUNDARY_ARN``), and
``emr-serverless:CreateApplication/TagResource``.
"""
from __future__ import annotations

import json
import logging
import time

from app.config import settings
from app.db.client import make_boto3_client
from app.db.models import ProvisioningStatus, Tenant
from app.services.dataplane_service import dataplane_client

logger = logging.getLogger("ml_platform.tenant_provisioning")

_PLATFORM_TAG = "ml-platform"


def _tags(tenant_id: str) -> list:
    """tenantId first (the ABAC key the runtime role scopes on) + platform."""
    return [
        {"Key": "tenantId", "Value": tenant_id},
        {"Key": "platform", "Value": _PLATFORM_TAG},
    ]


def _is_not_found(exc: Exception) -> bool:
    """True when a boto3 error means 'already gone' (teardown idempotency)."""
    marker = type(exc).__name__ + str(exc)
    return any(
        m in marker
        for m in ("ResourceNotFound", "NotFoundException", "NoSuchEntity")
    )


class TenantProvisioningService:
    def __init__(self) -> None:
        self.mock = settings.TENANT_PROVISIONING_MOCK_MODE

    def provision(self, tenant: Tenant, requested_by: str) -> Tenant:
        """Provision dataplane resources for ``tenant`` (idempotent).

        Mutates and returns ``tenant``; the caller persists it. Resource ids
        are written onto the tenant as each step completes, so a partial
        failure persists what exists and a retry resumes from there.
        """
        if self.mock:
            return self._mock_provision(tenant)
        tenant.provisioningStatus = ProvisioningStatus.PENDING.value
        tenant.provisioningError = None
        try:
            self._ensure_kms_key(tenant)
            self._ensure_execution_role(tenant)
            self._ensure_emr_application(tenant)
            tenant.s3BucketName = (
                f"s3://{settings.S3_ARTIFACTS_BUCKET}/{tenant.tenantId}/"
            )
            self._ensure_s3_prefix(tenant.tenantId)
            tenant.provisioningStatus = ProvisioningStatus.ACTIVE.value
            logger.info(
                "Provisioned tenant %s (requested by %s): app=%s role=%s",
                tenant.tenantId,
                requested_by,
                tenant.emrApplicationId,
                tenant.executionRoleArn,
            )
        except Exception as exc:
            # Partial ids already set on the tenant are persisted by the
            # caller; POST /tenants/{id}/provision re-drives from there.
            logger.exception("Provisioning failed for tenant %s", tenant.tenantId)
            tenant.provisioningStatus = ProvisioningStatus.FAILED.value
            tenant.provisioningError = str(exc)[:500]
        return tenant

    # ── Steps (each idempotent) ──────────────────────────────────────────

    def _ensure_kms_key(self, tenant: Tenant) -> None:
        if tenant.kmsKeyArn:
            return
        kms = dataplane_client("kms", tenant.tenantId, settings.KMS_ENDPOINT_URL)
        alias = f"alias/ml-platform-snowflake-{tenant.tenantId}"
        try:
            resp = kms.describe_key(KeyId=alias)
            tenant.kmsKeyArn = resp["KeyMetadata"]["Arn"]
            return
        except Exception:
            pass  # NotFound → create
        create_kwargs = {
            "Description": f"ml-platform Snowflake-token key for tenant {tenant.tenantId}",
            "Tags": [
                {"TagKey": t["Key"], "TagValue": t["Value"]}
                for t in _tags(tenant.tenantId)
            ],
        }
        # Account split: the backend decrypts this key cross-account with its
        # own credentials, which needs an explicit key-policy grant. The
        # dataplane account id comes from the runtime role ARN (both are set
        # together in split mode).
        if settings.BACKEND_PRINCIPAL_ARN and settings.DATAPLANE_RUNTIME_ROLE_ARN:
            dataplane_account = settings.DATAPLANE_RUNTIME_ROLE_ARN.split(":")[4]
            create_kwargs["Policy"] = json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Sid": "AccountRoot",
                            "Effect": "Allow",
                            "Principal": {
                                "AWS": f"arn:aws:iam::{dataplane_account}:root"
                            },
                            "Action": "kms:*",
                            "Resource": "*",
                        },
                        {
                            "Sid": "BackendUse",
                            "Effect": "Allow",
                            "Principal": {"AWS": settings.BACKEND_PRINCIPAL_ARN},
                            "Action": [
                                "kms:Encrypt",
                                "kms:Decrypt",
                                "kms:GenerateDataKey",
                                "kms:DescribeKey",
                            ],
                            "Resource": "*",
                        },
                    ],
                }
            )
        resp = kms.create_key(**create_kwargs)
        key = resp["KeyMetadata"]
        try:
            kms.create_alias(AliasName=alias, TargetKeyId=key["KeyId"])
        except Exception:
            logger.warning(
                "KMS alias %s could not be created (key %s still usable by ARN).",
                alias,
                key["KeyId"],
                exc_info=True,
            )
        tenant.kmsKeyArn = key["Arn"]

    def _ensure_execution_role(self, tenant: Tenant) -> None:
        if tenant.executionRoleArn:
            return
        iam = dataplane_client("iam", tenant.tenantId)
        role_name = f"ml-platform-tenant-{tenant.tenantId}-exec"
        trust = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Service": [
                            "emr-serverless.amazonaws.com",
                            "sagemaker.amazonaws.com",
                        ]
                    },
                    "Action": "sts:AssumeRole",
                }
            ],
        }
        create_kwargs = {
            "RoleName": role_name,
            "AssumeRolePolicyDocument": json.dumps(trust),
            "Description": f"ml-platform execution role for tenant {tenant.tenantId}",
            "Tags": _tags(tenant.tenantId),
        }
        # Orgs commonly allow runtime iam:CreateRole ONLY with the org
        # boundary attached (iam:PermissionsBoundary condition).
        if settings.TENANT_ROLE_PERMISSIONS_BOUNDARY_ARN:
            create_kwargs["PermissionsBoundary"] = (
                settings.TENANT_ROLE_PERMISSIONS_BOUNDARY_ARN
            )
        try:
            resp = iam.create_role(**create_kwargs)
            role_arn = resp["Role"]["Arn"]
        except Exception as exc:
            if "EntityAlreadyExists" not in type(exc).__name__ and (
                "EntityAlreadyExists" not in str(exc)
            ):
                raise
            role_arn = iam.get_role(RoleName=role_name)["Role"]["Arn"]
        bucket = settings.S3_ARTIFACTS_BUCKET
        secret_prefix = settings.SECRETS_MANAGER_JOB_TOKEN_PREFIX
        statements = [
            {
                "Sid": "TenantPrefixRW",
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                "Resource": f"arn:aws:s3:::{bucket}/{tenant.tenantId}/*",
            },
            {
                "Sid": "TenantPrefixList",
                "Effect": "Allow",
                "Action": ["s3:ListBucket"],
                "Resource": f"arn:aws:s3:::{bucket}",
                "Condition": {
                    "StringLike": {"s3:prefix": [f"{tenant.tenantId}/*"]}
                },
            },
            {
                "Sid": "TenantKmsUse",
                "Effect": "Allow",
                "Action": [
                    "kms:Decrypt",
                    "kms:Encrypt",
                    "kms:GenerateDataKey",
                    "kms:DescribeKey",
                ],
                "Resource": tenant.kmsKeyArn or "*",
            },
            # Jobs read their per-job secret; notebook kernels read (and
            # delete after reading) their session's Snowflake capability
            # secret. Both live under the job-token prefix, ABAC-scoped to
            # this tenant's tag. Deliberately NO secretsmanager:ListSecrets —
            # capability names must stay unenumerable
            # (docs/NOTEBOOK_SNOWFLAKE_OIDC.md, Tier 1).
            {
                "Sid": "JobTokenSecretsRead",
                "Effect": "Allow",
                "Action": ["secretsmanager:GetSecretValue"],
                "Resource": f"arn:aws:secretsmanager:*:*:secret:{secret_prefix}*",
                "Condition": {
                    "StringEquals": {"aws:ResourceTag/tenantId": tenant.tenantId}
                },
            },
            {
                "Sid": "SessionSecretDeleteAfterRead",
                "Effect": "Allow",
                "Action": ["secretsmanager:DeleteSecret"],
                "Resource": (
                    f"arn:aws:secretsmanager:*:*:secret:{secret_prefix}"
                    "snowflake-session/*"
                ),
                "Condition": {
                    "StringEquals": {"aws:ResourceTag/tenantId": tenant.tenantId}
                },
            },
            {
                "Sid": "JobLogs",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogGroups",
                    "logs:DescribeLogStreams",
                ],
                "Resource": "arn:aws:logs:*:*:*",
            },
        ]
        # Bucket objects are SSE-KMS with the artifacts CMK — without
        # data-key ops on it, every S3 read/write above fails. Blank in
        # local dev (unencrypted LocalStack bucket).
        if settings.S3_ARTIFACTS_KMS_KEY_ARN:
            statements.append(
                {
                    "Sid": "ArtifactsBucketKms",
                    "Effect": "Allow",
                    "Action": [
                        "kms:Decrypt",
                        "kms:GenerateDataKey",
                        "kms:DescribeKey",
                    ],
                    "Resource": settings.S3_ARTIFACTS_KMS_KEY_ARN,
                }
            )
        policy = {"Version": "2012-10-17", "Statement": statements}
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName="tenant-scope",
            PolicyDocument=json.dumps(policy),
        )
        tenant.executionRoleArn = role_arn

    def _ensure_emr_application(self, tenant: Tenant) -> None:
        if tenant.emrApplicationId:
            return
        emr = dataplane_client("emr-serverless", tenant.tenantId)
        resp = emr.create_application(
            name=f"ml-platform-{tenant.tenantId}",
            releaseLabel=settings.EMR_RELEASE_LABEL,
            type="SPARK",
            # Required for EMR Studio Workspace attach (docs/EMR_STUDIO_LAUNCH.md
            # §3 — "interactive endpoint enabled" is a hard dependency).
            interactiveConfiguration={
                "studioEnabled": True,
                "livyEndpointEnabled": True,
            },
            # Same request retried (e.g. re-driven provision racing a timeout)
            # returns the same application instead of a duplicate.
            clientToken=f"ml-platform-{tenant.tenantId}",
            tags={t["Key"]: t["Value"] for t in _tags(tenant.tenantId)},
        )
        tenant.emrApplicationId = resp["applicationId"]

    # ── Deprovisioning (hard tenant deletion) ────────────────────────────

    def deprovision(self, tenant: Tenant, delete_data: bool = False) -> Tenant:
        """Tear down the tenant's dataplane resources (idempotent, reverse
        order of provision).

        Fields are cleared from the tenant record as each teardown completes,
        so a partial failure persists what is left and re-running DELETE
        resumes from there. The KMS key is **scheduled** for deletion (30-day
        recovery window), never destroyed immediately. S3 data is deleted
        only when ``delete_data=True`` — the default keeps artifacts for
        governance/MRM retention.
        """
        if self.mock:
            tenant.emrApplicationId = None
            tenant.executionRoleArn = None
            tenant.kmsKeyArn = None
            tenant.provisioningStatus = ProvisioningStatus.PENDING.value
            tenant.provisioningError = None
            return tenant
        tenant.provisioningError = None
        try:
            self._teardown_emr_application(tenant)
            self._teardown_execution_role(tenant)
            self._teardown_kms_key(tenant)
            if delete_data:
                self._delete_s3_prefix(tenant.tenantId)
            tenant.provisioningStatus = ProvisioningStatus.PENDING.value
            logger.info(
                "Deprovisioned tenant %s (delete_data=%s)",
                tenant.tenantId,
                delete_data,
            )
        except Exception as exc:
            logger.exception("Deprovisioning failed for tenant %s", tenant.tenantId)
            tenant.provisioningStatus = ProvisioningStatus.FAILED.value
            tenant.provisioningError = str(exc)[:500]
        return tenant

    def _teardown_emr_application(self, tenant: Tenant) -> None:
        if not tenant.emrApplicationId:
            return
        emr = dataplane_client("emr-serverless", tenant.tenantId)
        app_id = tenant.emrApplicationId
        try:
            state = emr.get_application(applicationId=app_id)["application"]["state"]
        except Exception as exc:
            if _is_not_found(exc):
                tenant.emrApplicationId = None
                return
            raise
        # Deletion requires a stopped application; stopping is async.
        if state not in ("STOPPED", "CREATED"):
            emr.stop_application(applicationId=app_id)
            deadline = time.time() + 90
            while True:
                state = emr.get_application(applicationId=app_id)["application"]["state"]
                if state == "STOPPED":
                    break
                if time.time() > deadline:
                    raise RuntimeError(
                        f"EMR Serverless app {app_id} did not stop within 90s "
                        "— re-run DELETE to resume."
                    )
                time.sleep(3)
        emr.delete_application(applicationId=app_id)
        tenant.emrApplicationId = None

    def _teardown_execution_role(self, tenant: Tenant) -> None:
        if not tenant.executionRoleArn:
            return
        iam = dataplane_client("iam", tenant.tenantId)
        role_name = tenant.executionRoleArn.rsplit("/", 1)[-1]
        try:
            iam.delete_role_policy(RoleName=role_name, PolicyName="tenant-scope")
        except Exception as exc:
            if not _is_not_found(exc):
                raise
        try:
            iam.delete_role(RoleName=role_name)
        except Exception as exc:
            if not _is_not_found(exc):
                raise
        tenant.executionRoleArn = None

    def _teardown_kms_key(self, tenant: Tenant) -> None:
        if not tenant.kmsKeyArn:
            return
        kms = dataplane_client("kms", tenant.tenantId, settings.KMS_ENDPOINT_URL)
        alias = f"alias/ml-platform-snowflake-{tenant.tenantId}"
        try:
            kms.delete_alias(AliasName=alias)
        except Exception:
            pass  # best-effort — the schedule below is what matters
        try:
            kms.schedule_key_deletion(
                KeyId=tenant.kmsKeyArn, PendingWindowInDays=30
            )
        except Exception as exc:
            # Already pending deletion (KMSInvalidState) or gone → done.
            if not _is_not_found(exc) and "KMSInvalidState" not in (
                type(exc).__name__ + str(exc)
            ):
                raise
        tenant.kmsKeyArn = None

    def _delete_s3_prefix(self, tenant_id: str) -> None:
        """Delete every object under the tenant's prefix (explicit opt-in)."""
        bucket = settings.S3_ARTIFACTS_BUCKET
        client = make_boto3_client("s3", settings.S3_ENDPOINT_URL)
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=f"{tenant_id}/"):
            keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if keys:
                client.delete_objects(Bucket=bucket, Delete={"Objects": keys})

    # ── Mock mode ────────────────────────────────────────────────────────

    def _mock_provision(self, tenant: Tenant) -> Tenant:
        """Local dev: fill mock resource IDs and create the S3 prefix marker."""
        tenant.emrApplicationId = f"mock-emr-app-{tenant.tenantId}"
        tenant.executionRoleArn = (
            f"arn:aws:iam::000000000000:role/mock-{tenant.tenantId}-exec"
        )
        tenant.s3BucketName = f"s3://{settings.S3_ARTIFACTS_BUCKET}/{tenant.tenantId}/"
        tenant.provisioningStatus = ProvisioningStatus.ACTIVE.value
        self._ensure_s3_prefix(tenant.tenantId)
        return tenant

    def _ensure_s3_prefix(self, tenant_id: str) -> None:
        """Create the shared bucket (LocalStack) and the tenant's prefix marker
        so the S3 browser has somewhere to land. Best-effort — never fails
        tenant provisioning."""
        bucket = settings.S3_ARTIFACTS_BUCKET
        client = make_boto3_client("s3", settings.S3_ENDPOINT_URL)
        try:
            try:
                client.head_bucket(Bucket=bucket)
            except Exception:
                if settings.AWS_REGION == "us-east-1":
                    client.create_bucket(Bucket=bucket)
                else:
                    client.create_bucket(
                        Bucket=bucket,
                        CreateBucketConfiguration={
                            "LocationConstraint": settings.AWS_REGION
                        },
                    )
            client.put_object(Bucket=bucket, Key=f"{tenant_id}/.keep", Body=b"")
        except Exception:
            logger.warning(
                "Could not create S3 prefix for tenant %s.",
                tenant_id,
                exc_info=True,
            )


tenant_provisioning_service = TenantProvisioningService()
