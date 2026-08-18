"""Unit tests for notebook session launch.

The backend deep-links into EMR Studio (both auth modes) by returning the
Studio's static access URL — it makes no EMR Studio API call. These tests
cover that access-URL behavior plus the collaborative-fragment handling.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.services.notebook_service import NotebookService

STUDIO_URL = "https://es-EXAMPLE0000.emrstudio-prod.us-east-1.amazonaws.com"


@pytest.fixture
def real_mode(monkeypatch):
    """A NotebookService with mock modes off (exercise the real URL path)."""
    monkeypatch.setattr(settings, "EMR_MOCK_MODE", False)
    monkeypatch.setattr(settings, "SAGEMAKER_MOCK_MODE", False)
    return NotebookService()


def test_emr_launch_returns_studio_url(real_mode, monkeypatch):
    monkeypatch.setattr(settings, "EMR_STUDIO_URL", STUDIO_URL)
    assert real_mode.launch_emr_studio() == STUDIO_URL


def test_emr_launch_requires_url(real_mode, monkeypatch):
    monkeypatch.setattr(settings, "EMR_STUDIO_URL", None)
    with pytest.raises(RuntimeError) as exc:
        real_mode.launch_emr_studio()
    msg = str(exc.value)
    assert "EMR_STUDIO_URL" in msg
    # The message must point operators at the IAM-mode access grant, since the
    # backend deliberately does not presign.
    assert "CreateStudioPresignedUrl" in msg


def test_emr_launch_mock_mode():
    svc = NotebookService()
    svc.emr_mock = True
    url = svc.launch_emr_studio()
    assert url.startswith("https://mock-emr.local/")


def test_launch_is_auth_mode_independent(real_mode, monkeypatch):
    # The URL returned must not depend on EMR_AUTH_MODE — both modes deep-link
    # the same access URL.
    monkeypatch.setattr(settings, "EMR_STUDIO_URL", STUDIO_URL)
    for mode in ("IAM", "SSO"):
        monkeypatch.setattr(settings, "EMR_AUTH_MODE", mode)
        assert real_mode.launch_emr_studio() == STUDIO_URL


def test_launch_appends_collab_fragment(real_mode, monkeypatch):
    # The fragment is a best-effort breadcrumb (dropped by the SAML sign-in
    # hop; nothing AWS-side reads it) — but when appended it must be
    # well-formed and never a query param.
    monkeypatch.setattr(settings, "EMR_STUDIO_URL", STUDIO_URL)
    url, expires_at = real_mode.launch(
        "emr_studio", "tenant-a", "user-1", "DataScientist", usecase_id="UC-1043"
    )
    assert url == f"{STUDIO_URL}#collab=usecase:UC-1043"
    assert expires_at.endswith("Z")  # ISO-ish expiry stamp is returned


def test_launch_without_usecase_has_no_fragment(real_mode, monkeypatch):
    monkeypatch.setattr(settings, "EMR_STUDIO_URL", STUDIO_URL)
    url, _ = real_mode.launch("emr_studio", "tenant-a", "user-1", "DataScientist")
    assert "#collab" not in url


# ── SageMaker: user-profile ensure + per-tenant domain ───────────────────────


class FakeSageMaker:
    def __init__(self, profile_exists=True):
        self.profile_exists = profile_exists
        self.created = []
        self.presigned = []

    def describe_user_profile(self, DomainId, UserProfileName):
        if self.profile_exists:
            return {"Status": "InService"}
        raise Exception("ResourceNotFoundException")

    def create_user_profile(self, **kwargs):
        self.created.append(kwargs)
        self.profile_exists = True  # settles instantly in tests

    def create_presigned_domain_url(self, **kwargs):
        self.presigned.append(kwargs)
        return {"AuthorizedUrl": "https://presigned.example/session"}


class FakeTenantRepo:
    def __init__(self, tenant):
        self._tenant = tenant

    def get(self, tenant_id):
        return self._tenant


def _wire_sagemaker(monkeypatch, tenant, client):
    import app.db.repositories.tenant_repo as tenant_repo_module
    import app.services.notebook_service as ns

    monkeypatch.setattr(
        tenant_repo_module, "TenantRepository", lambda: FakeTenantRepo(tenant)
    )
    monkeypatch.setattr(ns, "make_boto3_client", lambda *a, **k: client)


def test_sagemaker_creates_missing_profile_with_tenant_role(real_mode, monkeypatch):
    from app.db.models import Tenant

    tenant = Tenant(
        tenantId="tenant-a", name="A",
        executionRoleArn="arn:aws:iam::1:role/ml-platform-tenant-tenant-a-exec",
    )
    monkeypatch.setattr(settings, "SAGEMAKER_DOMAIN_ID", "d-global")
    client = FakeSageMaker(profile_exists=False)
    _wire_sagemaker(monkeypatch, tenant, client)

    url = real_mode.launch_sagemaker_studio("tenant-a", "user-1", "a@b.com")
    assert url == "https://presigned.example/session"
    (created,) = client.created
    assert created["UserProfileName"] == "user-1"
    assert created["UserSettings"]["ExecutionRole"].endswith("tenant-a-exec")
    assert {"Key": "tenantId", "Value": "tenant-a"} in created["Tags"]
    assert {"Key": "email", "Value": "a@b.com"} in created["Tags"]


def test_sagemaker_existing_profile_not_recreated(real_mode, monkeypatch):
    from app.db.models import Tenant

    monkeypatch.setattr(settings, "SAGEMAKER_DOMAIN_ID", "d-global")
    client = FakeSageMaker(profile_exists=True)
    _wire_sagemaker(monkeypatch, Tenant(tenantId="tenant-a", name="A"), client)

    real_mode.launch_sagemaker_studio("tenant-a", "user-1")
    assert client.created == []
    assert client.presigned[0]["DomainId"] == "d-global"


def test_sagemaker_tenant_domain_wins_over_global(real_mode, monkeypatch):
    from app.db.models import Tenant

    monkeypatch.setattr(settings, "SAGEMAKER_DOMAIN_ID", "d-global")
    tenant = Tenant(tenantId="tenant-a", name="A", sagemakerDomainId="d-tenant")
    client = FakeSageMaker()
    _wire_sagemaker(monkeypatch, tenant, client)

    real_mode.launch_sagemaker_studio("tenant-a", "user-1")
    assert client.presigned[0]["DomainId"] == "d-tenant"


def test_sagemaker_requires_some_domain(real_mode, monkeypatch):
    from app.db.models import Tenant

    monkeypatch.setattr(settings, "SAGEMAKER_DOMAIN_ID", None)
    _wire_sagemaker(monkeypatch, Tenant(tenantId="tenant-a", name="A"), FakeSageMaker())
    with pytest.raises(RuntimeError) as exc:
        real_mode.launch_sagemaker_studio("tenant-a", "user-1")
    assert "sagemakerDomainId" in str(exc.value)
