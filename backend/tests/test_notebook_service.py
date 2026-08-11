"""Unit tests for the EMR Studio IAM-mode presign preflight.

``NotebookService._assert_studio_iam_mode`` guards ``CreateStudioPresignedUrl``
— which is only valid for IAM-auth-mode Studios — from being called against an
SSO Studio, where it otherwise fails deep in EMR with an opaque
``HashCsrf is null or empty`` 400. These tests exercise the staticmethod
directly with a fake ``emr`` client, so no AWS (or moto) is needed.
"""
from __future__ import annotations

import pytest

from app.services import notebook_service as ns
from app.services.notebook_service import NotebookService

STUDIO_ID = "es-EXAMPLE0000"


class FakeEmr:
    """Minimal stand-in for a boto3 ``emr`` client.

    ``describe_studio`` returns a Studio with the configured ``auth_mode`` (or
    raises ``error`` if given), and counts how many times it was called so a
    test can assert the per-Studio cache prevents a second describe.
    """

    def __init__(self, auth_mode: str | None = "IAM", error: Exception | None = None):
        self._auth_mode = auth_mode
        self._error = error
        self.describe_calls = 0

    def describe_studio(self, StudioId: str):  # noqa: N803 (boto3 kwarg casing)
        self.describe_calls += 1
        if self._error is not None:
            raise self._error
        return {"Studio": {"StudioId": StudioId, "AuthMode": self._auth_mode}}


@pytest.fixture(autouse=True)
def _clear_studio_cache():
    """The verified-Studio cache is module-global; isolate every test."""
    ns._verified_iam_studio_ids.clear()
    yield
    ns._verified_iam_studio_ids.clear()


def test_rejects_sso_studio():
    emr = FakeEmr(auth_mode="SSO")
    with pytest.raises(RuntimeError) as exc:
        NotebookService._assert_studio_iam_mode(emr, STUDIO_ID)
    msg = str(exc.value)
    # The error must name the actual mode and the opaque symptom, so the
    # operator can connect it to the 'HashCsrf' 500 they saw.
    assert "SSO" in msg
    assert "HashCsrf" in msg
    assert STUDIO_ID in msg
    # A misconfigured Studio must NOT be cached — it should keep failing loudly
    # until fixed, not be silently remembered as good.
    assert STUDIO_ID not in ns._verified_iam_studio_ids


def test_accepts_iam_studio_and_caches():
    emr = FakeEmr(auth_mode="IAM")
    # No raise for an IAM-mode Studio.
    NotebookService._assert_studio_iam_mode(emr, STUDIO_ID)
    assert STUDIO_ID in ns._verified_iam_studio_ids
    assert emr.describe_calls == 1


def test_cache_skips_second_describe():
    # First call verifies and caches.
    NotebookService._assert_studio_iam_mode(FakeEmr(auth_mode="IAM"), STUDIO_ID)
    # Second call with a client that would ERROR on describe must not touch it —
    # the immutable auth mode is already known.
    poisoned = FakeEmr(error=AssertionError("describe_studio should not be called"))
    NotebookService._assert_studio_iam_mode(poisoned, STUDIO_ID)
    assert poisoned.describe_calls == 0


def test_describe_failure_raises_config_hint():
    emr = FakeEmr(error=Exception("StudioNotFound"))
    with pytest.raises(RuntimeError) as exc:
        NotebookService._assert_studio_iam_mode(emr, STUDIO_ID)
    msg = str(exc.value)
    # A not-found / wrong-region / missing-permission describe points the
    # operator at the id + region, and preserves the original cause.
    assert "EMR_STUDIO_ID" in msg
    assert "region" in msg
    assert exc.value.__cause__ is not None
    assert STUDIO_ID not in ns._verified_iam_studio_ids


def test_unknown_auth_mode_rejected():
    # A Studio describe missing AuthMode (None) is not IAM -> reject.
    emr = FakeEmr(auth_mode=None)
    with pytest.raises(RuntimeError) as exc:
        NotebookService._assert_studio_iam_mode(emr, STUDIO_ID)
    assert "unknown" in str(exc.value)
    assert STUDIO_ID not in ns._verified_iam_studio_ids
