"""Launch presigned EMR Studio / SageMaker Studio notebook sessions.

In mock mode (``EMR_MOCK_MODE`` / ``SAGEMAKER_MOCK_MODE``) a fake session URL
is returned instantly so the full notebook-launch flow can be exercised
locally with no AWS account.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.db.client import make_boto3_client

_SESSION_TTL_SECONDS = 3600


class NotebookService:
    def __init__(self) -> None:
        self.emr_mock = settings.EMR_MOCK_MODE
        self.sagemaker_mock = settings.SAGEMAKER_MOCK_MODE

    def launch(self, session_type: str, tenant_id: str, user_id: str) -> tuple[str, str]:
        """Return ``(presigned_url, expires_at_iso)`` for the requested session type."""
        if session_type == "sagemaker_studio":
            url = self.launch_sagemaker_studio(tenant_id, user_id)
        else:
            url = self.launch_emr_studio(tenant_id, user_id)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=_SESSION_TTL_SECONDS)
        ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        return url, expires_at

    def launch_sagemaker_studio(self, tenant_id: str, user_id: str) -> str:
        if self.sagemaker_mock:
            return f"https://mock-studio.local/session/{uuid.uuid4()}"

        client = make_boto3_client("sagemaker")
        resp = client.create_presigned_domain_url(
            DomainId=settings.SAGEMAKER_DOMAIN_ID,
            UserProfileName=user_id,
            SessionExpirationDurationInSeconds=_SESSION_TTL_SECONDS,
        )
        return resp["AuthorizedUrl"]

    def launch_emr_studio(self, tenant_id: str, user_id: str) -> str:
        if self.emr_mock:
            return f"https://mock-emr.local/session/{uuid.uuid4()}"

        if not settings.EMR_STUDIO_ID:
            raise RuntimeError(
                "EMR_STUDIO_ID is not configured. An EMR Studio must be "
                "provisioned separately (AWS Console/IaC) — this app only "
                "requests a presigned login URL into an existing one."
            )
        client = make_boto3_client("emr")
        resp = client.create_studio_presigned_url(
            StudioId=settings.EMR_STUDIO_ID,
            SessionExpirationDurationInSeconds=_SESSION_TTL_SECONDS,
        )
        return resp["PresignedURL"]


notebook_service = NotebookService()
