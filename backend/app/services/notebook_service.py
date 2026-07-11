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

    def launch(
        self,
        session_type: str,
        tenant_id: str,
        user_id: str,
        usecase_id: str | None = None,
    ) -> tuple[str, str]:
        """Return ``(presigned_url, expires_at_iso)`` for the requested session type.

        When ``usecase_id`` is given the session opens in collaborative mode:
        the URL carries the use case as a fragment, which the Studio-side
        bootstrap uses to land everyone working on that use case in the same
        shared workspace. A fragment (not a query param) so it can never
        invalidate a presigned URL's signature.
        """
        if session_type == "sagemaker_studio":
            url = self.launch_sagemaker_studio(tenant_id, user_id)
        else:
            url = self.launch_emr_studio(tenant_id, user_id)
        if usecase_id:
            url = f"{url}#collab=usecase:{usecase_id}"
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
        """Return the SSO-mode Studio's access URL (a deep link).

        The Studio must be provisioned out-of-band in SSO/IAM-Identity-Center
        auth mode: the user's own Entra identity flows through natively, so
        notebook activity is attributable per user — no presigned URL and no
        shared platform identity involved.
        """
        if self.emr_mock:
            return f"https://mock-emr.local/session/{uuid.uuid4()}"

        if not settings.EMR_STUDIO_URL:
            raise RuntimeError(
                "EMR_STUDIO_URL is not configured. Provision an EMR Studio in "
                "SSO auth mode (AWS Console/IaC) and set its access URL — the "
                "platform only deep-links into it."
            )
        return settings.EMR_STUDIO_URL


notebook_service = NotebookService()
