"""Entra ID (Azure AD) OIDC token validation.

In ``prod`` mode the backend validates every JWT against the Entra ID JWKS
endpoint. JWKS keys are cached and refreshed every 15 minutes. In ``dev``
mode this module is not used — :mod:`app.dependencies` short-circuits to a
synthetic user before any validation runs.
"""
from __future__ import annotations

import re
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
    # Group overage: users in more than ~200 groups get no `groups` claim.
    # Entra instead emits a `_claim_names`/`_claim_sources` pointer telling
    # the API to fetch memberships from Microsoft Graph itself.
    claim_names = claims.get("_claim_names") or {}
    has_group_overage = isinstance(claim_names, dict) and "groups" in claim_names
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
        has_group_overage=has_group_overage,
        raw=claims,
    )


# ── Microsoft Graph group-overage resolution ────────────────────────────────
class GraphLookupError(Exception):
    """Raised when group membership cannot be resolved via Microsoft Graph."""


class _GraphTokenCache:
    """Client-credentials token for Microsoft Graph, cached until expiry."""

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._expires_at: float = 0.0
        self._lock = threading.Lock()

    def get(self) -> str:
        now = time.time()
        if self._token and now < self._expires_at - 60:
            return self._token
        with self._lock:
            now = time.time()
            if self._token and now < self._expires_at - 60:
                return self._token
            if not (
                settings.ENTRA_TENANT_ID
                and settings.ENTRA_CLIENT_ID
                and settings.ENTRA_CLIENT_SECRET
            ):
                raise GraphLookupError(
                    "Group overage requires ENTRA_CLIENT_SECRET (plus tenant/"
                    "client IDs) so the API can query Microsoft Graph."
                )
            try:
                with httpx.Client(timeout=10.0) as client:
                    resp = client.post(
                        f"https://login.microsoftonline.com/"
                        f"{settings.ENTRA_TENANT_ID}/oauth2/v2.0/token",
                        data={
                            "grant_type": "client_credentials",
                            "client_id": settings.ENTRA_CLIENT_ID,
                            "client_secret": settings.ENTRA_CLIENT_SECRET,
                            "scope": "https://graph.microsoft.com/.default",
                        },
                    )
                    resp.raise_for_status()
                    payload = resp.json()
            except httpx.HTTPError as exc:
                raise GraphLookupError(
                    f"Could not acquire a Microsoft Graph token: {exc}"
                ) from exc
            self._token = payload["access_token"]
            self._expires_at = now + int(payload.get("expires_in", 3600))
            return self._token


_graph_token_cache = _GraphTokenCache()

# Safety valve: 10 pages × 999 groups is far beyond any realistic membership.
_GRAPH_MAX_PAGES = 10

_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# Group names are stable enough to cache briefly; this keeps Graph off the
# hot path for repeat requests. Process-local, refreshed every 15 minutes.
_NAME_CACHE_TTL_SECONDS = 15 * 60
_name_cache: Dict[str, tuple[float, str]] = {}
_name_cache_lock = threading.Lock()


def fetch_group_names_via_graph(user_oid: str) -> list[str]:
    """Fetch a user's transitive group NAMES from Microsoft Graph.

    Used when the token carries a group-overage pointer instead of a
    ``groups`` claim. Requires the GroupMember.Read.All application
    permission (admin-consented) on the app registration.
    """
    token = _graph_token_cache.get()
    url = (
        f"https://graph.microsoft.com/v1.0/users/{user_oid}"
        f"/transitiveMemberOf/microsoft.graph.group"
        f"?$select=id,displayName&$top=999"
    )
    names: list[str] = []
    try:
        with httpx.Client(timeout=15.0) as client:
            for _ in range(_GRAPH_MAX_PAGES):
                resp = client.get(url, headers={"Authorization": f"Bearer {token}"})
                resp.raise_for_status()
                payload = resp.json()
                for item in payload.get("value", []):
                    if item.get("displayName"):
                        names.append(str(item["displayName"]))
                url = payload.get("@odata.nextLink")
                if not url:
                    break
    except httpx.HTTPError as exc:
        raise GraphLookupError(
            f"Microsoft Graph group lookup failed for user {user_oid}: {exc}"
        ) from exc
    return names


def _names_for_group_ids(group_ids: list[str]) -> list[str]:
    """Resolve group object IDs to display names via Graph ``getByIds``."""
    now = time.time()
    with _name_cache_lock:
        cached = {
            gid: name
            for gid, (fetched_at, name) in _name_cache.items()
            if now - fetched_at < _NAME_CACHE_TTL_SECONDS
        }
    missing = [gid for gid in group_ids if gid not in cached]

    if missing:
        token = _graph_token_cache.get()
        try:
            with httpx.Client(timeout=15.0) as client:
                # getByIds accepts up to 1000 ids per call.
                for start in range(0, len(missing), 1000):
                    resp = client.post(
                        "https://graph.microsoft.com/v1.0/directoryObjects/getByIds",
                        headers={"Authorization": f"Bearer {token}"},
                        json={
                            "ids": missing[start : start + 1000],
                            "types": ["group"],
                        },
                    )
                    resp.raise_for_status()
                    for item in resp.json().get("value", []):
                        gid, name = item.get("id"), item.get("displayName")
                        if gid and name:
                            cached[gid] = str(name)
                            with _name_cache_lock:
                                _name_cache[gid] = (now, str(name))
        except httpx.HTTPError as exc:
            raise GraphLookupError(
                f"Microsoft Graph group-name lookup failed: {exc}"
            ) from exc

    return [cached[gid] for gid in group_ids if gid in cached]


def get_group_names(payload: TokenPayload) -> list[str]:
    """Return the group NAMES for a validated token, whatever the claim holds.

    - Claim carries names (AD-synced groups emitting sAMAccountName): use
      them directly — no Graph call.
    - Claim carries object IDs (cloud-default): resolve names via Graph
      ``getByIds`` (cached).
    - No claim, overage pointer set (>200 groups): fetch transitive
      memberships from Graph.
    """
    if payload.groups:
        if all(_GUID_RE.match(g) for g in payload.groups):
            return _names_for_group_ids(payload.groups)
        return payload.groups
    if payload.has_group_overage:
        if not payload.user_id:
            raise GraphLookupError("Token has a group overage but no user OID.")
        return fetch_group_names_via_graph(payload.user_id)
    return []
