"""Unit tests for direct (boto3) tenant provisioning.

Fake clients stand in for KMS/IAM/EMR Serverless — these tests pin the
orchestration: ordering, idempotent resume, partial-failure state, tags,
and the interactive-endpoint flag EMR Studio attach depends on.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

import app.services.tenant_provisioning_service as tps
from app.config import settings
from app.db.models import ProvisioningStatus, Tenant


class FakeKms:
    def __init__(self):
        self.created = []
        self.deletions_scheduled = []

    def describe_key(self, KeyId):
        raise Exception("NotFoundException")

    def create_key(self, **kwargs):
        self.created.append(kwargs)
        return {"KeyMetadata": {"KeyId": "key-123", "Arn": "arn:aws:kms:us-east-1:1:key/key-123"}}

    def create_alias(self, **kwargs):
        return {}

    def delete_alias(self, **kwargs):
        return {}

    def schedule_key_deletion(self, **kwargs):
        self.deletions_scheduled.append(kwargs)
        return {}


class FakeIam:
    def __init__(self):
        self.created = []
        self.policies = []
        self.deleted_roles = []
        self.role_gone = False

    def create_role(self, **kwargs):
        self.created.append(kwargs)
        return {"Role": {"Arn": f"arn:aws:iam::1:role/{kwargs['RoleName']}"}}

    def get_role(self, RoleName):
        return {"Role": {"Arn": f"arn:aws:iam::1:role/{RoleName}"}}

    def put_role_policy(self, **kwargs):
        self.policies.append(kwargs)
        return {}

    def delete_role_policy(self, **kwargs):
        if self.role_gone:
            raise Exception("NoSuchEntityException")
        return {}

    def delete_role(self, RoleName):
        if self.role_gone:
            raise Exception("NoSuchEntityException")
        self.deleted_roles.append(RoleName)
        return {}


class FakeEmr:
    def __init__(self, fail=False):
        self.created = []
        self.deleted = []
        self.fail = fail
        self.state = "STARTED"
        self.stop_calls = 0

    def create_application(self, **kwargs):
        if self.fail:
            raise Exception("AccessDeniedException: not allowed")
        self.created.append(kwargs)
        return {"applicationId": "app-123"}

    def get_application(self, applicationId):
        return {"application": {"state": self.state}}

    def stop_application(self, applicationId):
        self.stop_calls += 1
        self.state = "STOPPED"  # stop instantly in tests
        return {}

    def delete_application(self, applicationId):
        if self.fail:
            raise Exception("AccessDeniedException: not allowed")
        self.deleted.append(applicationId)
        return {}


@pytest.fixture
def fakes(monkeypatch):
    clients: Dict[str, Any] = {"kms": FakeKms(), "iam": FakeIam(), "emr-serverless": FakeEmr()}
    monkeypatch.setattr(
        tps, "dataplane_client", lambda service, tenant_id, endpoint_url=None: clients[service]
    )
    # S3 prefix marker is best-effort; stub it out entirely.
    monkeypatch.setattr(
        tps.TenantProvisioningService, "_ensure_s3_prefix", lambda self, t: None
    )
    return clients


def _svc():
    svc = tps.TenantProvisioningService()
    svc.mock = False
    return svc


def test_direct_provision_happy_path(fakes):
    tenant = _svc().provision(Tenant(tenantId="t-a", name="A"), requested_by="admin")
    assert tenant.provisioningStatus == ProvisioningStatus.ACTIVE.value
    assert tenant.provisioningError is None
    assert tenant.kmsKeyArn and tenant.executionRoleArn and tenant.emrApplicationId
    assert tenant.s3BucketName == f"s3://{settings.S3_ARTIFACTS_BUCKET}/t-a/"
    # Role name matches the PassRole pattern the task role is granted.
    assert "ml-platform-tenant-t-a-exec" in tenant.executionRoleArn


def test_emr_app_has_interactive_endpoint_and_client_token(fakes):
    _svc().provision(Tenant(tenantId="t-a", name="A"), requested_by="admin")
    (call,) = fakes["emr-serverless"].created
    # EMR Studio Workspace attach depends on the interactive endpoint.
    assert call["interactiveConfiguration"] == {
        "studioEnabled": True,
        "livyEndpointEnabled": True,
    }
    assert call["clientToken"] == "ml-platform-t-a"
    assert call["tags"]["tenantId"] == "t-a"


def test_resources_are_tagged_for_abac(fakes):
    _svc().provision(Tenant(tenantId="t-a", name="A"), requested_by="admin")
    (role_call,) = fakes["iam"].created
    assert {"Key": "tenantId", "Value": "t-a"} in role_call["Tags"]
    (key_call,) = fakes["kms"].created
    assert {"TagKey": "tenantId", "TagValue": "t-a"} in key_call["Tags"]


def test_exec_role_policy_grants_job_and_session_secrets(fakes):
    """Jobs read their secret; notebook kernels read + delete their session
    capability secret; logs are writable — and ListSecrets is NEVER granted
    (capability names must stay unenumerable)."""
    import json

    _svc().provision(Tenant(tenantId="t-a", name="A"), requested_by="admin")
    (policy_call,) = fakes["iam"].policies
    doc = json.loads(policy_call["PolicyDocument"])
    sids = {s["Sid"]: s for s in doc["Statement"]}
    read = sids["JobTokenSecretsRead"]
    assert read["Condition"]["StringEquals"]["aws:ResourceTag/tenantId"] == "t-a"
    assert settings.SECRETS_MANAGER_JOB_TOKEN_PREFIX in read["Resource"]
    delete = sids["SessionSecretDeleteAfterRead"]
    assert "snowflake-session/" in delete["Resource"]
    assert "JobLogs" in sids
    assert "ListSecrets" not in json.dumps(doc)


def test_exec_role_policy_artifacts_kms_only_when_configured(fakes, monkeypatch):
    import json

    monkeypatch.setattr(
        settings, "S3_ARTIFACTS_KMS_KEY_ARN", "arn:aws:kms:us-east-1:1:key/cmk"
    )
    _svc().provision(Tenant(tenantId="t-a", name="A"), requested_by="admin")
    (policy_call,) = fakes["iam"].policies
    doc = json.loads(policy_call["PolicyDocument"])
    sids = {s["Sid"]: s for s in doc["Statement"]}
    assert sids["ArtifactsBucketKms"]["Resource"] == "arn:aws:kms:us-east-1:1:key/cmk"


def test_partial_failure_keeps_created_ids_and_marks_failed(fakes):
    fakes["emr-serverless"].fail = True
    tenant = _svc().provision(Tenant(tenantId="t-a", name="A"), requested_by="admin")
    assert tenant.provisioningStatus == ProvisioningStatus.FAILED.value
    assert "AccessDenied" in (tenant.provisioningError or "")
    # KMS + role completed before the failure — persisted for the retry.
    assert tenant.kmsKeyArn and tenant.executionRoleArn
    assert tenant.emrApplicationId is None


def test_retry_resumes_skipping_existing_resources(fakes):
    tenant = Tenant(
        tenantId="t-a",
        name="A",
        kmsKeyArn="arn:aws:kms:us-east-1:1:key/existing",
        executionRoleArn="arn:aws:iam::1:role/existing",
        provisioningStatus=ProvisioningStatus.FAILED.value,
        provisioningError="old error",
    )
    tenant = _svc().provision(tenant, requested_by="admin")
    assert tenant.provisioningStatus == ProvisioningStatus.ACTIVE.value
    assert tenant.provisioningError is None
    assert fakes["kms"].created == []  # skipped
    assert fakes["iam"].created == []  # skipped
    assert tenant.emrApplicationId == "app-123"  # only the missing piece


def test_permissions_boundary_attached_when_configured(fakes, monkeypatch):
    monkeypatch.setattr(
        settings,
        "TENANT_ROLE_PERMISSIONS_BOUNDARY_ARN",
        "arn:aws:iam::1:policy/CSEStandardPermissionsBoundary",
    )
    _svc().provision(Tenant(tenantId="t-a", name="A"), requested_by="admin")
    (role_call,) = fakes["iam"].created
    assert role_call["PermissionsBoundary"].endswith("CSEStandardPermissionsBoundary")


def test_mock_mode_unchanged(monkeypatch):
    svc = tps.TenantProvisioningService()
    svc.mock = True
    monkeypatch.setattr(
        tps.TenantProvisioningService, "_ensure_s3_prefix", lambda self, t: None
    )
    tenant = svc.provision(Tenant(tenantId="t-a", name="A"), requested_by="admin")
    assert tenant.provisioningStatus == ProvisioningStatus.ACTIVE.value
    assert tenant.emrApplicationId == "mock-emr-app-t-a"


# ── deprovision (hard deletion) ──────────────────────────────────────────────


def _provisioned_tenant():
    return Tenant(
        tenantId="t-a",
        name="A",
        emrApplicationId="app-123",
        executionRoleArn="arn:aws:iam::1:role/ml-platform-tenant-t-a-exec",
        kmsKeyArn="arn:aws:kms:us-east-1:1:key/key-123",
        provisioningStatus=ProvisioningStatus.ACTIVE.value,
    )


def test_deprovision_tears_down_everything(fakes, monkeypatch):
    deleted_prefixes = []
    monkeypatch.setattr(
        tps.TenantProvisioningService,
        "_delete_s3_prefix",
        lambda self, t: deleted_prefixes.append(t),
    )
    tenant = _svc().deprovision(_provisioned_tenant())
    assert tenant.emrApplicationId is None
    assert tenant.executionRoleArn is None
    assert tenant.kmsKeyArn is None
    assert tenant.provisioningStatus == ProvisioningStatus.PENDING.value
    # Running app was stopped before deletion.
    emr = fakes["emr-serverless"]
    assert emr.stop_calls == 1 and emr.deleted == ["app-123"]
    assert fakes["iam"].deleted_roles == ["ml-platform-tenant-t-a-exec"]
    # KMS key SCHEDULED for deletion with the recovery window, not destroyed.
    (sched,) = fakes["kms"].deletions_scheduled
    assert sched["PendingWindowInDays"] == 30
    # Data kept by default.
    assert deleted_prefixes == []


def test_deprovision_deletes_data_only_on_opt_in(fakes, monkeypatch):
    deleted_prefixes = []
    monkeypatch.setattr(
        tps.TenantProvisioningService,
        "_delete_s3_prefix",
        lambda self, t: deleted_prefixes.append(t),
    )
    _svc().deprovision(_provisioned_tenant(), delete_data=True)
    assert deleted_prefixes == ["t-a"]


def test_deprovision_tolerates_already_gone_role(fakes):
    fakes["iam"].role_gone = True
    tenant = _svc().deprovision(_provisioned_tenant())
    assert tenant.provisioningStatus == ProvisioningStatus.PENDING.value
    assert tenant.executionRoleArn is None


def test_deprovision_partial_failure_resumable(fakes):
    fakes["emr-serverless"].fail = True  # delete_application raises
    tenant = _svc().deprovision(_provisioned_tenant())
    assert tenant.provisioningStatus == ProvisioningStatus.FAILED.value
    assert "AccessDenied" in (tenant.provisioningError or "")
    # EMR id retained for the retry; later steps never ran.
    assert tenant.emrApplicationId == "app-123"
    assert tenant.executionRoleArn is not None
    assert fakes["kms"].deletions_scheduled == []


def test_deprovision_mock_mode_clears_fields():
    svc = tps.TenantProvisioningService()
    svc.mock = True
    tenant = svc.deprovision(_provisioned_tenant())
    assert tenant.emrApplicationId is None
    assert tenant.kmsKeyArn is None
    assert tenant.provisioningStatus == ProvisioningStatus.PENDING.value
