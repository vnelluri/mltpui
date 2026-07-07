"""Derive (role, tenant) memberships from Entra security-group NAMES.

The naming convention is the source of truth — there is no mapping table:

- ``GROUP_NAME_PLATFORM_ADMIN`` / ``GROUP_NAME_MRM``: fixed names for the two
  platform-wide roles (tenantId is always None).
- ``GROUP_NAME_PATTERN``: regex with named captures ``tenant`` and ``role``
  for tenant-scoped groups, e.g. ``myapp-risk-analytics-datascientist``.

All matching is case-insensitive (AD group names are case-insensitive).
A parsed tenant that has no Tenant record grants nothing — so a rogue group
named for a nonexistent tenant is inert. The security precondition (creation
of convention-named groups reserved to the governed IGA process) is
documented on the settings in app/config.py.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from app.auth.models import Membership
from app.config import settings
from app.db.models import ROLE_PRECEDENCE, Role

logger = logging.getLogger("ml_platform.membership")

# Pattern capture value -> canonical platform role.
_ROLE_SEGMENT_MAP = {
    "datascientist": Role.DATA_SCIENTIST.value,
    "tenantadmin": Role.TENANT_ADMIN.value,
}

_precedence_rank = {role: i for i, role in enumerate(ROLE_PRECEDENCE)}


class MembershipService:
    def __init__(self) -> None:
        self._pattern = re.compile(settings.GROUP_NAME_PATTERN, re.IGNORECASE)
        self._platform_admin = settings.GROUP_NAME_PLATFORM_ADMIN.lower()
        self._mrm = settings.GROUP_NAME_MRM.lower()

    def memberships_from_group_names(self, names: List[str]) -> List[Membership]:
        """Parse group names into the user's full membership set.

        Non-matching names are ignored (users belong to plenty of unrelated
        groups). Result is de-duplicated and sorted highest-privilege first,
        so index 0 is the default active membership.
        """
        found: Dict[tuple, Membership] = {}
        candidate_tenants: set[str] = set()

        for raw in names:
            name = (raw or "").strip()
            lowered = name.lower()
            if lowered == self._platform_admin:
                found[(Role.PLATFORM_ADMIN.value, None)] = Membership(
                    role=Role.PLATFORM_ADMIN.value, tenantId=None, groupName=name
                )
                continue
            if lowered == self._mrm:
                found[(Role.MRM.value, None)] = Membership(
                    role=Role.MRM.value, tenantId=None, groupName=name
                )
                continue
            match = self._pattern.match(name)
            if not match:
                continue
            role = _ROLE_SEGMENT_MAP.get(match.group("role").lower())
            if role is None:
                continue
            tenant_id = match.group("tenant").lower()
            candidate_tenants.add(tenant_id)
            found.setdefault(
                (role, tenant_id),
                Membership(role=role, tenantId=tenant_id, groupName=name),
            )

        # A group naming a tenant that doesn't exist grants nothing.
        existing = self._existing_tenants(candidate_tenants)
        memberships = [
            m
            for (role, tenant_id), m in found.items()
            if tenant_id is None or tenant_id in existing
        ]
        dropped = candidate_tenants - existing
        if dropped:
            logger.warning(
                "Ignoring convention groups for unknown tenant(s): %s",
                ", ".join(sorted(dropped)),
            )

        memberships.sort(
            key=lambda m: (
                _precedence_rank.get(m.role, len(ROLE_PRECEDENCE)),
                m.tenantId or "",
            )
        )
        return memberships

    @staticmethod
    def _existing_tenants(candidate_tenant_ids: set[str]) -> set[str]:
        if not candidate_tenant_ids:
            return set()
        from app.db.repositories.tenant_repo import TenantRepository

        repo = TenantRepository()
        return {tid for tid in candidate_tenant_ids if repo.get(tid) is not None}


def select_active_membership(
    memberships: List[Membership],
    requested_role: Optional[str],
    requested_tenant: Optional[str],
) -> Optional[Membership]:
    """Pick the active membership for this request.

    With no explicit request, the highest-privilege membership wins. An
    explicit request must exactly match one of the user's memberships —
    returns None otherwise (callers reject the request), so switching can
    never grant anything AD didn't.
    """
    if not memberships:
        return None
    if not requested_role:
        return memberships[0]
    requested_tenant = requested_tenant or None
    for m in memberships:
        if m.matches(requested_role, requested_tenant):
            return m
    return None


membership_service = MembershipService()
