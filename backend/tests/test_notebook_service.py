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
