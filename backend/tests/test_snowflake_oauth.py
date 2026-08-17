"""Unit tests for the Entra OAuth pieces of the Snowflake integration.

Covers the HMAC-signed OAuth state (the identity binding for the redirect
callback), the authorize-URL builder, and token-bundle parsing. Network
calls (code redemption / refresh) are not exercised here — their request
shape is trivial and the interesting logic is in what surrounds them.
"""
from __future__ import annotations

import pytest

import app.services.snowflake_service as sf
from app.config import settings
from app.services.snowflake_service import (
    SnowflakeService,
    make_oauth_state,
    verify_oauth_state,
)


# ── OAuth state ──────────────────────────────────────────────────────────────


def test_state_roundtrip():
    state = make_oauth_state("user-1", "a@b.com", "tenant-x", "DataScientist")
    claims = verify_oauth_state(state)
    assert claims is not None
    assert claims["u"] == "user-1"
    assert claims["e"] == "a@b.com"
    assert claims["t"] == "tenant-x"
    assert claims["r"] == "DataScientist"


def test_state_tenantless_user():
    state = make_oauth_state("user-2", "c@d.com", None, "PlatformAdmin")
    claims = verify_oauth_state(state)
    assert claims is not None and claims["t"] is None


def test_state_rejects_tampered_signature():
    state = make_oauth_state("user-1", "a@b.com", None, "DataScientist")
    body, sig = state.split(".", 1)
    flipped = ("0" if sig[0] != "0" else "1") + sig[1:]
    assert verify_oauth_state(f"{body}.{flipped}") is None


def test_state_rejects_tampered_body():
    state = make_oauth_state("user-1", "a@b.com", None, "DataScientist")
    body, sig = state.split(".", 1)
    assert verify_oauth_state(f"X{body[1:]}.{sig}") is None


def test_state_rejects_garbage():
    assert verify_oauth_state("") is None
    assert verify_oauth_state("no-dot-here") is None


def test_state_expires(monkeypatch):
    monkeypatch.setattr(sf, "_STATE_TTL_SECONDS", -1)
    state = make_oauth_state("user-1", "a@b.com", None, "DataScientist")
    assert verify_oauth_state(state) is None


def test_state_key_binds_to_client_secret(monkeypatch):
    state = make_oauth_state("user-1", "a@b.com", None, "DataScientist")
    monkeypatch.setattr(settings, "SNOWFLAKE_OAUTH_CLIENT_SECRET", "rotated")
    # A state minted under the old key must not verify under a new one.
    assert verify_oauth_state(state) is None


# ── Authorize URL ────────────────────────────────────────────────────────────


@pytest.fixture
def oauth_settings(monkeypatch):
    monkeypatch.setattr(settings, "ENTRA_TENANT_ID", "tid-123")
    monkeypatch.setattr(settings, "SNOWFLAKE_OAUTH_CLIENT_ID", "client-abc")
    monkeypatch.setattr(settings, "SNOWFLAKE_OAUTH_SCOPE", "api://sf/session:scope:analyst")
    monkeypatch.setattr(settings, "PLATFORM_API_BASE_URL", "https://api.example.com")


def test_authorize_url_contains_oauth_params(oauth_settings):
    url = SnowflakeService().build_authorize_url("the-state")
    assert url.startswith("https://login.microsoftonline.com/tid-123/oauth2/v2.0/authorize?")
    assert "client_id=client-abc" in url
    assert "response_type=code" in url
    assert "state=the-state" in url
    assert "offline_access" in url  # refresh token — background re-mint
    # Redirect back into the API's callback route.
    assert "api.example.com%2Fsnowflake%2Foauth%2Fcallback" in url


def test_authorize_url_requires_config(monkeypatch):
    monkeypatch.setattr(settings, "ENTRA_TENANT_ID", None)
    with pytest.raises(RuntimeError):
        SnowflakeService().build_authorize_url("s")


# ── Token bundle parsing ─────────────────────────────────────────────────────


def test_token_bundle_shape():
    bundle = SnowflakeService._token_bundle(
        {"access_token": "at", "refresh_token": "rt", "expires_in": 60},
        email="a@b.com",
    )
    assert bundle["access_token"] == "at"
    assert bundle["refresh_token"] == "rt"
    assert bundle["email"] == "a@b.com"
    assert bundle["expires_at"].endswith("Z")
    assert bundle["refresh_expires_at"] > bundle["expires_at"]


def test_token_bundle_without_refresh():
    bundle = SnowflakeService._token_bundle({"access_token": "at"})
    assert bundle["refresh_token"] is None
    assert "email" not in bundle


def test_mock_connect_shape():
    token, username, expires_at = SnowflakeService().mock_connect("jane.doe@corp.com")
    assert token.startswith("mock-sf-token-")
    assert username == "JANE.DOE"
    assert expires_at.endswith("Z")


# ── ensure_valid_cache (refresh decision) ────────────────────────────────────


def _cache(expires_in_s: int, refresh: str | None = None):
    from datetime import datetime, timedelta, timezone

    from app.db.models import SnowflakeTokenCache

    return SnowflakeTokenCache(
        userId="user-1",
        snowflakeToken="kms:AAAA",
        snowflakeRefreshToken=refresh,
        expiresAt=(
            datetime.now(timezone.utc) + timedelta(seconds=expires_in_s)
        ).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        snowflakeUsername="USER",
    )


def _user():
    from app.auth.models import CurrentUser

    return CurrentUser(
        userId="user-1", email="a@b.com", name="A", role="DataScientist",
        tenantId="tenant-x",
    )


def test_ensure_valid_cache_returns_fresh_token(monkeypatch):
    import app.routers.snowflake as router

    monkeypatch.setattr(router._token_repo, "get", lambda uid: _cache(3600))
    assert router.ensure_valid_cache(_user()).snowflakeUsername == "USER"


def test_ensure_valid_cache_respects_min_validity(monkeypatch):
    """A token inside the runway window without a refresh token → 400."""
    from fastapi import HTTPException

    import app.routers.snowflake as router

    monkeypatch.setattr(router._token_repo, "get", lambda uid: _cache(300))
    # Valid without runway…
    assert router.ensure_valid_cache(_user()) is not None
    # …but 5 minutes left < 10-minute runway, and nothing to refresh from.
    with pytest.raises(HTTPException) as exc:
        router.ensure_valid_cache(_user(), min_validity_seconds=600)
    assert exc.value.status_code == 400


def test_ensure_valid_cache_never_connected(monkeypatch):
    from fastapi import HTTPException

    import app.routers.snowflake as router

    monkeypatch.setattr(router._token_repo, "get", lambda uid: None)
    with pytest.raises(HTTPException):
        router.ensure_valid_cache(_user())
