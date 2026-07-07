"""Resolve Entra group OIDs to a (role, tenantId) tuple.

The GroupMapping table is the single source of truth. When a user belongs to
multiple mapped groups, the highest-privilege role wins (PlatformAdmin > MRM
> TenantAdmin > DataScientist). The tenantId is taken from the mapping that
provided the winning role.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from app.db.models import ROLE_PRECEDENCE, GroupMapping
from app.db.repositories.group_mapping_repo import GroupMappingRepository


@dataclass
class ResolvedGroup:
    role: str
    tenantId: Optional[str]
    groupId: str


class GroupResolverService:
    def __init__(self, repo: Optional[GroupMappingRepository] = None) -> None:
        self.repo = repo or GroupMappingRepository()

    def resolve(self, group_ids: List[str]) -> Optional[ResolvedGroup]:
        """Resolve a list of Entra group OIDs to the winning role/tenant.

        Returns ``None`` if no group maps to any role.
        """
        mappings: List[GroupMapping] = self.repo.resolve_groups(group_ids)
        if not mappings:
            return None

        # Pick the mapping with the highest-privilege role.
        best: Optional[GroupMapping] = None
        best_rank = len(ROLE_PRECEDENCE)
        for mapping in mappings:
            try:
                rank = ROLE_PRECEDENCE.index(mapping.role)
            except ValueError:
                # Unknown role value — treat as lowest privilege.
                rank = len(ROLE_PRECEDENCE)
            if rank < best_rank:
                best_rank = rank
                best = mapping

        if best is None:
            return None
        return ResolvedGroup(
            role=best.role, tenantId=best.tenantId, groupId=best.groupId
        )
