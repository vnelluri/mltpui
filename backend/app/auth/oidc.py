"""Entra ID (Azure AD) OIDC token validation.

In ``prod`` mode the backend validates every JWT against the Entra ID JWKS
endpoint. JWKS keys are cached and refreshed every 15 minutes. In ``dev``
mode this module is not used — :mod:`app.dependencies` short-circuits to a
synthetic user before any validation runs.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

import httpx
from jose import jwt
from jose.exceptions import JWTError

from app.auth.models import TokenPayload
from app.config import settings

_JWKS_TTL_SECONDS = 15 * 60


class _JwksCache:
    """Simple TTL cache of the Entra ID JWKS document."""

    def __init__(self) -> None:
        self._keys: Optional[Dict[str, Any]] = None
        self._fetched_at: float = 0.0
        self._lock = threading.Lock()

    def get_keys(self, force: bool = False) -> Dict[str, Any]:
        now = time.time()
        if (
            not force
            and self._keys is not None
            and (now - self._fetched_at) < _JWKS_TTL_SECONDS
        ):
            return self._keys
        with self._lock:
            now = time.time()
            if (
                not force
                and self._keys is not None
                and (now - self._fetched_at) < _JWKS_TTL_SECONDS
            ):
                return self._keys
            url = settings.jwks_url
            if not url:
                raise RuntimeError(
                    "ENTRA_TENANT_ID is not configured; cannot fetch JWKS."
                )
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url)
                resp.raise_for_status()
                doc = resp.json()
            self._keys = {key["kid"]: key for key in doc.get("keys", [])}
            self._fetched_at = now
            return self._keys

    def find_key(self, kid: str) -> Optional[Dict[str, Any]]:
        keys = self.get_keys()
        key = keys.get(kid)
        if key is None:
            # Key rotation: force a refresh once and retry.
            keys = self.get_keys(force=True)
            key = keys.get(kid)
        return key


_jwks_cache = _JwksCache()


class TokenValidationError(Exception):
    """Raised when a JWT fails validation."""


def validate_token(token: str) -> TokenPayload:
    """Validate an Entra ID access/ID token and return its claims.

    Verifies signature (RS256 against JWKS), audience and issuer.
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as exc:  # pragma: no cover - malformed token
        raise TokenValidationError(f"Malformed token header: {exc}") from exc

    kid = unverified_header.get("kid")
    if not kid:
        raise TokenValidationError("Token header missing 'kid'.")

    jwk = _jwks_cache.find_key(kid)
    if jwk is None:
        raise TokenValidationError("Signing key not found in JWKS.")

    audience = settings.ENTRA_AUDIENCE or settings.ENTRA_CLIENT_ID
    try:
        claims = jwt.decode(
            token,
            jwk,
            algorithms=["RS256"],
            audience=audience,
            issuer=settings.issuer,
            options={
                "verify_aud": audience is not None,
                "verify_iss": settings.issuer is not None,
            },
        )
    except JWTError as exc:
        raise TokenValidationError(f"Token validation failed: {exc}") from exc

    return _claims_to_payload(claims)


def decode_unverified(token: str) -> TokenPayload:
    """Decode a token WITHOUT signature verification (dev token-info only)."""
    try:
        claims = jwt.get_unverified_claims(token)
    except JWTError as exc:
        raise TokenValidationError(f"Could not decode token: {exc}") from exc
    return _claims_to_payload(claims)


def _claims_to_payload(claims: Dict[str, Any]) -> TokenPayload:
    groups = claims.get("groups") or []
    if not isinstance(groups, list):
        groups = [groups]
    return TokenPayload(
        oid=claims.get("oid"),
        sub=claims.get("sub"),
        email=claims.get("email"),
        preferred_username=claims.get("preferred_username") or claims.get("upn"),
        name=claims.get("name"),
        tid=claims.get("tid"),
        aud=claims.get("aud"),
        iss=claims.get("iss"),
        groups=[str(g) for g in groups],
        raw=claims,
    )
