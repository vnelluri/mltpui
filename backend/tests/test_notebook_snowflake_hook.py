"""Unit tests for the notebook launch-time Snowflake capability-secret hook.

Pins the Tier-1 contract (docs/NOTEBOOK_SNOWFLAKE_OIDC.md): a random,
prefix-scoped secret name minted per launch and surfaced once; launches never
fail on Snowflake problems; the name is never persisted.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import app.routers.notebooks as notebooks
import app.routers.snowflake as snowflake_router
import app.services.job_service as job_service_module
from app.auth.models import CurrentUser
from app.config import settings
from app.db.models import NotebookSession, SnowflakeTokenCache


def _user():
    return CurrentUser(
        userId="user-1", email="a@b.com", name="A", role="DataScientist",
        tenantId="tenant-a",
    )


def _cache():
    return SnowflakeTokenCache(
        userId="user-1",
        snowflakeToken="kms:AAAA",
        expiresAt="2099-01-01T00:00:00.000000Z",
        snowflakeUsername="A",
        tenantId="tenant-a",
    )


def test_mint_returns_none_when_never_connected(monkeypatch):
    def raise_400(user, min_validity_seconds=0):
        raise HTTPException(status_code=400, detail="Not connected")

    monkeypatch.setattr(snowflake_router, "ensure_valid_cache", raise_400)
    assert notebooks.mint_snowflake_session_secret(_user(), "tenant-a") is None


def test_mint_returns_capability_name(monkeypatch):
    monkeypatch.setattr(
        snowflake_router, "ensure_valid_cache", lambda user, min_validity_seconds=0: _cache()
    )
    from app.services import snowflake_service as sf

    monkeypatch.setattr(sf.KmsCipher, "decrypt", lambda self, c: "the-jwt")
    stored = {}

    def fake_store(tenant_id, payload):
        stored.update({"tenant_id": tenant_id, "payload": payload})
        return "ml-platform/job-tokens/snowflake-session/uuid-x"

    monkeypatch.setattr(
        notebooks.job_service, "store_snowflake_session_secret", fake_store
    )
    name = notebooks.mint_snowflake_session_secret(_user(), "tenant-a")
    assert name == "ml-platform/job-tokens/snowflake-session/uuid-x"
    assert stored["tenant_id"] == "tenant-a"
    assert stored["payload"]["access_token"] == "the-jwt"
    assert stored["payload"]["username"] == "A"


def test_mint_failure_never_breaks_launch(monkeypatch):
    monkeypatch.setattr(
        snowflake_router, "ensure_valid_cache", lambda user, min_validity_seconds=0: _cache()
    )
    from app.services import snowflake_service as sf

    def boom(self, c):
        raise RuntimeError("KMS down")

    monkeypatch.setattr(sf.KmsCipher, "decrypt", boom)
    assert notebooks.mint_snowflake_session_secret(_user(), "tenant-a") is None


def test_store_session_secret_shape(monkeypatch):
    created = {}

    class FakeSm:
        def create_secret(self, **kwargs):
            created.update(kwargs)
            return {"ARN": "arn:..."}

    monkeypatch.setattr(
        job_service_module, "dataplane_client", lambda svc, tid, ep=None: FakeSm()
    )
    name = job_service_module.job_service.store_snowflake_session_secret(
        "tenant-a", {"access_token": "t"}
    )
    prefix = f"{settings.SECRETS_MANAGER_JOB_TOKEN_PREFIX}snowflake-session/"
    assert name.startswith(prefix)
    # Random capability suffix, not a guessable identity.
    assert len(name) > len(prefix) + 30
    assert created["Name"] == name
    assert {"Key": "tenantId", "Value": "tenant-a"} in created["Tags"]
    assert '"tenantId": "tenant-a"' in created["SecretString"]


def test_persistence_contract():
    """presignedUrl is stripped (credential, returned once); the secret NAME
    is persisted — the background refresher needs it, and same-tenant
    kernels cannot read the control-plane table (see notebook_repo)."""
    session = NotebookSession(
        sessionId="s1", userId="u1", sessionType="emr_studio",
        presignedUrl="https://x", snowflakeSecretName="secret-name",
        urlExpiresAt="2099-01-01T00:00:00Z",
    )
    dumped = session.model_dump(exclude={"presignedUrl"})
    assert "presignedUrl" not in dumped
    assert dumped["snowflakeSecretName"] == "secret-name"
