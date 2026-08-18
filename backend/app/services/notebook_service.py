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

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.db.client import make_boto3_client

logger = logging.getLogger("ml_platform.notebook")

_SESSION_TTL_SECONDS = 3600
# create_user_profile is asynchronous — how long to wait for InService
# before presigning (profiles typically settle in seconds).
_PROFILE_READY_TIMEOUT_SECONDS = 60


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
        user_email: str | None = None,
    ) -> tuple[str, str]:
        """Return ``(url, expires_at_iso)`` for the requested session type.

        When ``usecase_id`` is given the launch is collaborative *by
        convention*: collaborators create/join a Workspace named
        ``usecase-<id>`` in the Studio and use EMR Studio's built-in
        collaboration; the platform records ``usecaseId`` on the session
        (governance metadata) and the UI surfaces the convention. The
        ``#collab=usecase:<id>`` fragment appended here is a best-effort
        breadcrumb only — nothing AWS-side reads it, and it does not survive
        the SAML sign-in hop (the HTTP-POST binding drops fragments), so no
        code may depend on it. A fragment (not a query param) so it can
        never invalidate a SageMaker presigned URL's signature.

        ``role`` is accepted for parity with the router/audit call site; the
        EMR access-URL path is role-independent (tiering is enforced by the
        user's own IAM permissions on the Studio, not by this code).
        """
        if session_type == "sagemaker_studio":
            url = self.launch_sagemaker_studio(tenant_id, user_id, user_email)
        else:
            url = self.launch_emr_studio()
        if usecase_id:
            url = f"{url}#collab=usecase:{usecase_id}"
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=_SESSION_TTL_SECONDS)
        ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        return url, expires_at

    def launch_sagemaker_studio(
        self, tenant_id: str, user_id: str, user_email: str | None = None
    ) -> str:
        if self.sagemaker_mock:
            return f"https://mock-studio.local/session/{uuid.uuid4()}"

        # Tenant-specific domain wins; the platform-wide setting is the
        # single-domain fallback.
        from app.db.repositories.tenant_repo import TenantRepository

        tenant = TenantRepository().get(tenant_id)
        domain_id = (
            tenant.sagemakerDomainId if tenant else None
        ) or settings.SAGEMAKER_DOMAIN_ID
        if not domain_id:
            raise RuntimeError(
                "No SageMaker domain configured: set Tenant.sagemakerDomainId "
                "or the platform-wide SAGEMAKER_DOMAIN_ID."
            )
        client = make_boto3_client("sagemaker")
        self._ensure_user_profile(
            client,
            domain_id,
            user_id,
            tenant_id,
            execution_role_arn=tenant.executionRoleArn if tenant else None,
            user_email=user_email,
        )
        resp = client.create_presigned_domain_url(
            DomainId=domain_id,
            UserProfileName=user_id,
            SessionExpirationDurationInSeconds=_SESSION_TTL_SECONDS,
        )
        return resp["AuthorizedUrl"]

    @staticmethod
    def _ensure_user_profile(
        client,
        domain_id: str,
        user_id: str,
        tenant_id: str,
        execution_role_arn: str | None = None,
        user_email: str | None = None,
    ) -> None:
        """Idempotently ensure the user's Studio profile exists.

        ``CreatePresignedDomainUrl`` requires the profile to already exist —
        without this, every user's first real-mode launch fails with
        ResourceNotFound. The profile name is the platform ``userId`` (a
        Cognito sub — SageMaker profile names cannot contain ``@``, so the
        email goes on a tag for human-readable attribution instead).

        The profile pins the tenant's execution role, so kernels get the
        same tenant-scoped identity as EMR notebooks and training jobs.
        For per-user CloudTrail attribution, enable
        ``ExecutionRoleIdentityConfig=USER_PROFILE_NAME`` on the domain —
        SageMaker then stamps the profile name as ``SourceIdentity``.
        """
        try:
            client.describe_user_profile(
                DomainId=domain_id, UserProfileName=user_id
            )
            return
        except Exception as exc:
            if "ResourceNotFound" not in (type(exc).__name__ + str(exc)):
                raise
        tags = [{"Key": "tenantId", "Value": tenant_id}]
        if user_email:
            tags.append({"Key": "email", "Value": user_email})
        create_kwargs: dict = {
            "DomainId": domain_id,
            "UserProfileName": user_id,
            "Tags": tags,
        }
        if execution_role_arn:
            create_kwargs["UserSettings"] = {"ExecutionRole": execution_role_arn}
        client.create_user_profile(**create_kwargs)
        logger.info(
            "Created SageMaker user profile %s in domain %s (tenant %s)",
            user_id,
            domain_id,
            tenant_id,
        )
        # Profile creation is async; presigning a Pending profile fails.
        deadline = time.time() + _PROFILE_READY_TIMEOUT_SECONDS
        while True:
            status = client.describe_user_profile(
                DomainId=domain_id, UserProfileName=user_id
            )["Status"]
            if status == "InService":
                return
            if status in ("Failed", "Delete_Failed"):
                raise RuntimeError(
                    f"SageMaker user profile {user_id} entered {status}."
                )
            if time.time() > deadline:
                raise RuntimeError(
                    f"SageMaker user profile {user_id} not InService within "
                    f"{_PROFILE_READY_TIMEOUT_SECONDS}s — retry the launch."
                )
            time.sleep(2)

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
