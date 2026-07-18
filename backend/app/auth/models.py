"""Auth-related Pydantic models: decoded token payload and current user."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.db.models import Role

# Machine principal role for training-run tokens (never held by humans, not
# part of ROLE_PRECEDENCE — every require_role() guard rejects it by default).
MACHINE_ROLE = "JobRun"


class TokenPayload(BaseModel):
    """Subset of the validated Cognito ID-token claims we rely on.

    The SAML identity provider's attribute mapping populates ``email``,
    ``given_name`` and ``custom:groups`` (comma-separated Azure AD group
    names, parsed into ``groups`` by app.auth.cognito).
    """

    sub: Optional[str] = None
    email: Optional[str] = None
    given_name: Optional[str] = None
    aud: Optional[str] = None
    iss: Optional[str] = None
    token_use: Optional[str] = None
    groups: List[str] = Field(default_factory=list)
    # Raw claims retained for /auth/token-info in dev.
    raw: dict = Field(default_factory=dict)

    @property
    def user_id(self) -> Optional[str]:
        return self.sub

    @property
    def user_email(self) -> Optional[str]:
        return self.email

    @property
    def display_name(self) -> Optional[str]:
        return self.given_name or self.email or self.sub


class Membership(BaseModel):
    """One (role, tenant) pair derived from a convention-named AD group."""

    role: str
    tenantId: Optional[str] = None
    # Display name from the Tenant record — enriched by /auth/me so the UI
    # can show meaningful names (the group name only carries the tenant id).
    tenantName: Optional[str] = None
    # The group name that granted this membership (attribution/debugging).
    groupName: Optional[str] = None

    def matches(self, role: str, tenant_id: Optional[str]) -> bool:
        return self.role == role and self.tenantId == (tenant_id or None)


class CurrentUser(BaseModel):
    """The authenticated principal for the current request.

    ``role``/``tenantId`` are the ACTIVE membership (what every downstream
    check reads); ``memberships`` is everything the user's AD groups grant.
    The active pair is selected per-request via the X-Active-Role /
    X-Active-Tenant headers and always validated against ``memberships`` —
    switching can select among grants, never elevate beyond them.
    """

    userId: str
    email: str
    name: str
    role: str
    tenantId: Optional[str] = None
    memberships: List[Membership] = Field(default_factory=list)
    resolvedFromGroupId: Optional[str] = None
    # Machine principals only (run tokens): the single run this identity may
    # write to. Always None for human users.
    machineJobId: Optional[str] = None
    machineExperimentId: Optional[str] = None
    machineRunId: Optional[str] = None
    # The user's raw bearer token (prod: the Cognito ID token) — used for
    # Snowflake token exchange. Never persisted or logged.
    accessToken: Optional[str] = Field(default=None, exclude=True)

    @property
    def is_machine(self) -> bool:
        return self.role == MACHINE_ROLE

    @property
    def is_platform_admin(self) -> bool:
        return self.role == Role.PLATFORM_ADMIN.value

    @property
    def is_mrm(self) -> bool:
        return self.role == Role.MRM.value

    @property
    def is_tenant_admin(self) -> bool:
        return self.role == Role.TENANT_ADMIN.value

    @property
    def is_data_scientist(self) -> bool:
        return self.role == Role.DATA_SCIENTIST.value

    @property
    def sees_all_tenants(self) -> bool:
        """PlatformAdmin and MRM have cross-tenant read visibility."""
        return self.role in (Role.PLATFORM_ADMIN.value, Role.MRM.value)

    def can_access_tenant(self, tenant_id: Optional[str]) -> bool:
        """Return True if this user may access resources in ``tenant_id``."""
        if self.sees_all_tenants:
            return True
        if tenant_id is None:
            return False
        return self.tenantId == tenant_id
