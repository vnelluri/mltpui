"""Launch EMR Studio / SageMaker Studio notebook sessions.

The backend **deep-links** into notebook environments — it never presigns EMR
Studio itself. For both EMR Studio auth modes the platform returns the Studio's
static **access URL** and lets AWS's hosted sign-in flow authenticate the user
and mint the presigned URL server-side:

- ``IAM`` mode: the access URL redirects to the IAM sign-in (or, with IAM
  federation to your IdP, the IdP portal). "Assigning" a user is purely an IAM
  grant of ``elasticmapreduce:CreateStudioPresignedUrl`` on the Studio ARN —
  the hosted flow calls that action, not us. (``CreateStudioPresignedUrl`` is
  not in the boto3 SDK; it is not meant to be called directly — see
  ``docs/EMR_STUDIO_IAM_MODE.md``.)
- ``SSO`` mode: the access URL redirects to IAM Identity Center, which supplies
  each user's Entra identity.

Either way the app just returns ``EMR_STUDIO_URL`` — the auth mode is a property
of how the *Studio* is configured, not of this code path. SageMaker Studio is
the one place we presign (``sagemaker:CreatePresignedDomainUrl``), using the
backend's own credentials against a per-user domain profile.

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
        role: str,
        usecase_id: str | None = None,
    ) -> tuple[str, str]:
        """Return ``(url, expires_at_iso)`` for the requested session type.

        When ``usecase_id`` is given the session opens in collaborative mode:
        the URL carries the use case as a fragment, which the Studio-side
        bootstrap uses to land everyone working on that use case in the same
        shared workspace. A fragment (not a query param) so it can never
        invalidate a SageMaker presigned URL's signature.

        ``role`` is accepted for parity with the router/audit call site; the
        EMR access-URL path is role-independent (tiering is enforced by the
        user's own IAM permissions on the Studio, not by this code).
        """
        if session_type == "sagemaker_studio":
            url = self.launch_sagemaker_studio(tenant_id, user_id)
        else:
            url = self.launch_emr_studio()
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

    def launch_emr_studio(self) -> str:
        """Return the EMR Studio access URL to deep-link the user into.

        The same static URL for both auth modes: AWS's hosted sign-in flow
        (Identity Center for SSO, or IAM / IAM-federation for IAM mode)
        authenticates the user at that URL and presigns them into the Studio.
        The backend makes no EMR Studio API call.
        """
        if self.emr_mock:
            return f"https://mock-emr.local/session/{uuid.uuid4()}"

        if not settings.EMR_STUDIO_URL:
            raise RuntimeError(
                "EMR_STUDIO_URL is not configured. Provision an EMR Studio "
                "(AWS Console/IaC) and set its access URL — the platform only "
                "deep-links into it; AWS's hosted sign-in flow authenticates "
                "the user. For IAM auth mode, grant users "
                "elasticmapreduce:CreateStudioPresignedUrl on the Studio ARN so "
                "that flow can complete (see docs/EMR_STUDIO_IAM_MODE.md)."
            )
        return settings.EMR_STUDIO_URL


notebook_service = NotebookService()
