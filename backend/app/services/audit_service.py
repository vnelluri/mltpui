"""Audit event helper — called from every mutating route."""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import Request

from app.auth.models import CurrentUser
from app.db.models import AuditEvent, utcnow_iso
from app.db.repositories.audit_repo import AuditRepository


class AuditService:
    def __init__(self, repo: Optional[AuditRepository] = None) -> None:
        self.repo = repo or AuditRepository()

    def record(
        self,
        *,
        user: CurrentUser,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        request: Optional[Request] = None,
    ) -> AuditEvent:
        """Persist an audit event and return it."""
        ip_address = None
        user_agent = None
        if request is not None:
            ip_address = request.client.host if request.client else None
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                ip_address = forwarded.split(",")[0].strip()
            user_agent = request.headers.get("user-agent")

        event = AuditEvent(
            eventId=str(uuid.uuid4()),
            tenantId=tenant_id if tenant_id is not None else user.tenantId,
            userId=user.userId,
            action=action,
            resourceType=resource_type,
            resourceId=resource_id,
            timestamp=utcnow_iso(),
            ipAddress=ip_address,
            userAgent=user_agent,
            details=details or {},
        )
        return self.repo.create(event)


# Module-level singleton for convenience.
audit_service = AuditService()
