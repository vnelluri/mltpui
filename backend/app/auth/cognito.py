"""Amazon Cognito ID-token validation (Azure AD federated via SAML).

The React app signs in through the Cognito Hosted UI, which federates to
Azure AD (Entra ID) over SAML. Cognito issues the JWTs; the backend
validates the **ID token** — the org-standard user-info carrier — against
the user pool's JWKS. JWKS keys are cached and refreshed every 15 minutes.

User info comes entirely from the ID-token claims mapped by the SAML
identity provider's attribute mapping:

- ``email``          — the user's email address
- ``given_name``     — the user's given name
- ``custom:groups``  — comma-separated Azure AD group NAMES

Because group names arrive directly in the token, no Microsoft Graph
lookups are needed (the old Entra OIDC path resolved GUID claims and
>200-group overages via Graph).

In ``dev`` mode this module is not used — :mod:`app.dependencies`
short-circuits to a synthetic user before any validation runs.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

import httpx
from jose import jwt
from jose.exceptions import JWTError

from app.auth.models import TokenPayload
from app.config import settings

_JWKS_TTL_SECONDS = 15 * 60


class _JwksCache:
    """Simple TTL cache of the Cognito user pool's JWKS document."""

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
                    "COGNITO_USER_POOL_ID is not configured; cannot fetch JWKS."
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
    """Validate a Cognito ID token and return its claims.

    Verifies signature (RS256 against the user pool JWKS), audience (the
    app client ID), issuer (the user pool), and that the token is an ID
    token (``token_use == "id"`` — access tokens carry no user attributes).
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

    audience = settings.COGNITO_APP_CLIENT_ID
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

    if claims.get("token_use") != "id":
        raise TokenValidationError(
            "Expected a Cognito ID token (token_use='id'); got "
            f"'{claims.get('token_use')}'. User info is read from the ID "
            "token — send it as the Bearer credential, not the access token."
        )

    return _claims_to_payload(claims)


def decode_unverified(token: str) -> TokenPayload:
    """Decode a token WITHOUT signature verification (dev token-info only)."""
    try:
        claims = jwt.get_unverified_claims(token)
    except JWTError as exc:
        raise TokenValidationError(f"Could not decode token: {exc}") from exc
    return _claims_to_payload(claims)


def parse_groups_claim(value: Any) -> List[str]:
    """Parse the ``custom:groups`` claim into a list of group names.

    The claim is a comma-separated string of Azure AD group names. Cognito
    flattens multi-valued SAML attributes into one string and (depending on
    the IdP) may wrap it in square brackets — tolerate both forms, plus a
    genuine JSON list for forward compatibility.
    """
    if isinstance(value, list):
        return [str(g).strip() for g in value if str(g).strip()]
    if not isinstance(value, str):
        return []
    cleaned = value.strip()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1]
    return [g.strip() for g in cleaned.split(",") if g.strip()]


def _claims_to_payload(claims: Dict[str, Any]) -> TokenPayload:
    return TokenPayload(
        sub=claims.get("sub"),
        email=claims.get("email"),
        given_name=claims.get("given_name"),
        aud=claims.get("aud"),
        iss=claims.get("iss"),
        token_use=claims.get("token_use"),
        groups=parse_groups_claim(claims.get("custom:groups")),
        raw=claims,
    )
