"""Unit tests for the background Snowflake session-secret refresher.

Pins the contract: only active sessions with a secret name are touched, the
secret is rewritten under its EXISTING name (the pasted value keeps
working), a disconnected user is skipped without killing the pass, and mock
mode never starts the thread.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import app.services.session_refresh_service as srs
from app.config import settings
from app.db.models import NotebookSession, SnowflakeTokenCache


def _session(**overrides):
    defaults = dict(
        sessionId="s1", userId="user-1", tenantId="tenant-a",
        sessionType="emr_studio", urlExpiresAt="2099-01-01T00:00:00Z",
        snowflakeSecretName="ml-platform/job-tokens/snowflake-session/uuid-1",
        status="active",
    )
    defaults.update(overrides)
    return NotebookSession(**defaults)


def _cache():
    return SnowflakeTokenCache(
        userId="user-1", snowflakeToken="kms:AAAA",
        expiresAt="2099-01-01T00:00:00.000000Z", snowflakeUsername="A",
        tenantId="tenant-a",
    )


@pytest.fixture
def wired(monkeypatch):
    """Wire fakes into one refresh pass; returns the recording dicts."""
    calls = {"ensured": [], "stored": []}

    class FakeRepo:
        def __init__(self, sessions):
            self._sessions = sessions

        def list_active(self, max_age_hours):
            return self._sessions

    def wire(sessions, ensure=None):
        monkeypatch.setattr(srs, "NotebookRepository", lambda: FakeRepo(sessions))
        import app.routers.snowflake as sf_router

        def default_ensure(user_id, tenant_id, min_validity_seconds=0):
            calls["ensured"].append((user_id, tenant_id, min_validity_seconds))
            return _cache()

        monkeypatch.setattr(
            sf_router, "ensure_valid_cache_by_ids", ensure or default_ensure
        )
        from app.services import snowflake_service as sf

        monkeypatch.setattr(sf.KmsCipher, "decrypt", lambda self, c: "fresh-jwt")
        import app.services.job_service as js

        def fake_store(tenant_id, payload, name=None):
            calls["stored"].append({"tenant_id": tenant_id, "payload": payload, "name": name})
            return name or "new-name"

        monkeypatch.setattr(
            js.job_service, "store_snowflake_session_secret", fake_store
        )
        return calls

    return wire


def test_refreshes_under_existing_name(wired):
    calls = wired([_session()])
    assert srs.refresh_active_session_secrets() == 1
    (stored,) = calls["stored"]
    # Same capability name — the value the user pasted keeps working.
    assert stored["name"] == "ml-platform/job-tokens/snowflake-session/uuid-1"
    assert stored["payload"]["access_token"] == "fresh-jwt"
    # Demanded runway outlives the next tick.
    (_, _, min_validity) = calls["ensured"][0]
    assert min_validity > settings.SNOWFLAKE_SESSION_REFRESH_INTERVAL_SECONDS


def test_skips_sessions_without_secret_or_tenant(wired):
    calls = wired([
        _session(snowflakeSecretName=None),
        _session(sessionId="s2", tenantId=None),
    ])
    assert srs.refresh_active_session_secrets() == 0
    assert calls["stored"] == []


def test_disconnected_user_skipped_pass_survives(wired):
    def ensure(user_id, tenant_id, min_validity_seconds=0):
        if user_id == "user-1":
            raise HTTPException(status_code=400, detail="Not connected")
        return _cache()

    calls = wired(
        [_session(), _session(sessionId="s2", userId="user-2")], ensure=ensure
    )
    # user-1 disconnected → skipped; user-2 still refreshed.
    assert srs.refresh_active_session_secrets() == 1
    assert calls["stored"][0]["name"].endswith("uuid-1")


def test_mock_mode_never_starts_thread(monkeypatch):
    started = []
    import threading

    monkeypatch.setattr(settings, "SNOWFLAKE_MOCK_MODE", True)
    monkeypatch.setattr(
        threading, "Thread",
        lambda *a, **k: started.append(1) or type("T", (), {"start": lambda s: None})(),
    )
    srs.start_session_refresher()
    assert started == []


def test_zero_interval_disables(monkeypatch):
    started = []
    import threading

    monkeypatch.setattr(settings, "SNOWFLAKE_MOCK_MODE", False)
    monkeypatch.setattr(settings, "SNOWFLAKE_SESSION_REFRESH_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(
        threading, "Thread",
        lambda *a, **k: started.append(1) or type("T", (), {"start": lambda s: None})(),
    )
    srs.start_session_refresher()
    assert started == []
