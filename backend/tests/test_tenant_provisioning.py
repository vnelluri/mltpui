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

    def describe_key(self, KeyId):
        raise Exception("NotFoundException")

    def create_key(self, **kwargs):
        self.created.append(kwargs)
        return {"KeyMetadata": {"KeyId": "key-123", "Arn": "arn:aws:kms:us-east-1:1:key/key-123"}}

    def create_alias(self, **kwargs):
        return {}


class FakeIam:
    def __init__(self):
        self.created = []
        self.policies = []

    def create_role(self, **kwargs):
        self.created.append(kwargs)
        return {"Role": {"Arn": f"arn:aws:iam::1:role/{kwargs['RoleName']}"}}

    def get_role(self, RoleName):
        return {"Role": {"Arn": f"arn:aws:iam::1:role/{RoleName}"}}

    def put_role_policy(self, **kwargs):
        self.policies.append(kwargs)
        return {}


class FakeEmr:
    def __init__(self, fail=False):
        self.created = []
        self.fail = fail

    def create_application(self, **kwargs):
        if self.fail:
            raise Exception("AccessDeniedException: not allowed")
        self.created.append(kwargs)
        return {"applicationId": "app-123"}


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
