"""Launch EMR Studio / SageMaker Studio notebook sessions.

EMR Studio has two auth modes (``EMR_AUTH_MODE``):

- ``IAM`` (default): no Identity Center — assume the user's tier role and call
  ``CreateStudioPresignedUrl``, mirroring the SageMaker presign path. See
  ``docs/EMR_STUDIO_IAM_MODE.md``.
- ``SSO``: return the static Studio URL; Identity Center supplies the user's
  Entra identity. No AWS API call.

In mock mode (``EMR_MOCK_MODE`` / ``SAGEMAKER_MOCK_MODE``) a fake session URL
is returned instantly so the full notebook-launch flow can be exercised
locally with no AWS account.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.db.client import make_boto3_client
from app.db.models import Role

_SESSION_TTL_SECONDS = 3600
# An EMR Studio IAM-mode presigned URL must be *redeemed* within a short window
# (~5 min) — far shorter than the notional 1-hour session. Reflect that in the
# stored urlExpiresAt so the UI doesn't invite a user to relaunch a dead link
# from history.
_EMR_IAM_PRESIGN_TTL_SECONDS = 300

# Active role -> EMR Studio tier, mirroring the SSO session-policy tiers.
# DataScientist attaches + runs (basic); Tenant/Platform admins additionally
# manage EMR Serverless applications (intermediate). Only these two roles reach
# a launch (the router restricts to TenantAdmin | DataScientist).
_EMR_TIER_BY_ROLE = {
    Role.DATA_SCIENTIST.value: "basic",
    Role.TENANT_ADMIN.value: "intermediate",
    Role.PLATFORM_ADMIN.value: "intermediate",
}

# STS RoleSessionName allows [\w+=,.@-] and max 64 chars.
_ROLE_SESSION_NAME_RE = re.compile(r"[^\w+=,.@-]")

# Studio ids whose IAM auth mode has been verified this process. A Studio's
# auth mode is immutable, so once confirmed IAM we never describe it again —
# the preflight costs one API call per Studio id, not one per launch.
_verified_iam_studio_ids: set[str] = set()


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
        """Return ``(presigned_url, expires_at_iso)`` for the requested session type.

        When ``usecase_id`` is given the session opens in collaborative mode:
        the URL carries the use case as a fragment, which the Studio-side
        bootstrap uses to land everyone working on that use case in the same
        shared workspace. A fragment (not a query param) so it can never
        invalidate a presigned URL's signature.
        """
        ttl = _SESSION_TTL_SECONDS
        if session_type == "sagemaker_studio":
            url = self.launch_sagemaker_studio(tenant_id, user_id)
        else:
            url = self.launch_emr_studio(tenant_id, user_id, role)
            if settings.EMR_AUTH_MODE == "IAM" and not self.emr_mock:
                ttl = _EMR_IAM_PRESIGN_TTL_SECONDS
        if usecase_id:
            url = f"{url}#collab=usecase:{usecase_id}"
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=ttl)
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

    def launch_emr_studio(self, tenant_id: str, user_id: str, role: str) -> str:
        """Return an EMR Studio deep link for the user.

        SSO mode: the static Studio access URL — the user's Entra identity flows
        through Identity Center natively.

        IAM mode: no Identity Center. Assume the tier role for the user's role
        (``RoleSessionName`` = the user's stable id, so EMR Studio's
        ``creatorUserId`` = ``${aws:userId}`` Workspace ownership is per-user and
        stable across logins) and call ``CreateStudioPresignedUrl``.
        """
        if self.emr_mock:
            return f"https://mock-emr.local/session/{uuid.uuid4()}"

        if settings.EMR_AUTH_MODE == "IAM":
            return self._launch_emr_studio_iam(tenant_id, user_id, role)

        if not settings.EMR_STUDIO_URL:
            raise RuntimeError(
                "EMR_STUDIO_URL is not configured. Provision an EMR Studio in "
                "SSO auth mode (AWS Console/IaC) and set its access URL — the "
                "platform only deep-links into it."
            )
        return settings.EMR_STUDIO_URL

    def _launch_emr_studio_iam(self, tenant_id: str, user_id: str, role: str) -> str:
        if not settings.EMR_STUDIO_ID:
            raise RuntimeError(
                "EMR_AUTH_MODE=IAM but EMR_STUDIO_ID is not configured "
                "(the id of the IAM-auth-mode Studio to presign into)."
            )
        tier = _EMR_TIER_BY_ROLE.get(role)
        role_arn = {
            "basic": settings.EMR_STUDIO_BASIC_ROLE_ARN,
            "intermediate": settings.EMR_STUDIO_INTERMEDIATE_ROLE_ARN,
        }.get(tier)
        if not role_arn:
            raise RuntimeError(
                f"No EMR Studio tier role configured for role '{role}' "
                f"(tier '{tier}'). Set EMR_STUDIO_{(tier or '').upper()}_ROLE_ARN."
            )

        # Stable, sanitized RoleSessionName — the same user must map to the same
        # aws:userId every login so they retain ownership of their Workspaces.
        session_name = _ROLE_SESSION_NAME_RE.sub("-", user_id)[:64]
        sts = make_boto3_client("sts", settings.STS_ENDPOINT_URL)
        creds = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName=session_name,
            DurationSeconds=_SESSION_TTL_SECONDS,
            Tags=[
                {"Key": "user", "Value": session_name},
                {"Key": "tenantId", "Value": tenant_id},
            ],
        )["Credentials"]
        emr = make_boto3_client(
            "emr",
            credentials={
                "aws_access_key_id": creds["AccessKeyId"],
                "aws_secret_access_key": creds["SecretAccessKey"],
                "aws_session_token": creds["SessionToken"],
            },
            cache_key=f"emr-studio:{session_name}:{int(creds['Expiration'].timestamp())}",
        )
        self._assert_studio_iam_mode(emr, settings.EMR_STUDIO_ID)
        return emr.create_studio_presigned_url(StudioId=settings.EMR_STUDIO_ID)[
            "AuthorizedUrl"
        ]

    @staticmethod
    def _assert_studio_iam_mode(emr, studio_id: str) -> None:
        """Preflight the Studio's auth mode before presigning.

        ``CreateStudioPresignedUrl`` is only valid for IAM-auth-mode Studios.
        Against an SSO (Identity Center) Studio it fails deep inside EMR with an
        opaque ``HashCsrf is null or empty`` 400 — impossible to diagnose from
        the call site. Describe the Studio once and fail with a self-explaining
        error instead. Auth mode is immutable, so the result is cached per
        Studio id (see ``_verified_iam_studio_ids``).
        """
        if studio_id in _verified_iam_studio_ids:
            return
        try:
            studio = emr.describe_studio(StudioId=studio_id)["Studio"]
        except Exception as e:  # not-found, wrong region, or missing permission
            raise RuntimeError(
                f"EMR Studio preflight failed: could not describe Studio "
                f"'{studio_id}' in region '{settings.AWS_REGION}'. Verify "
                f"EMR_STUDIO_ID is correct and the Studio lives in this region. "
                f"({e})"
            ) from e
        auth_mode = studio.get("AuthMode")
        if auth_mode != "IAM":
            raise RuntimeError(
                f"EMR Studio '{studio_id}' is in {auth_mode or 'unknown'} auth "
                "mode, but EMR_AUTH_MODE=IAM requires an IAM-auth-mode Studio: "
                "CreateStudioPresignedUrl is only valid for IAM Studios (against "
                "an SSO Studio it fails with 'HashCsrf is null or empty'). Point "
                "EMR_STUDIO_ID at the IAM-mode Studio (the emr-studio module's "
                "studio_id output); auth mode is immutable, so an SSO Studio must "
                "be recreated as IAM."
            )
        _verified_iam_studio_ids.add(studio_id)


notebook_service = NotebookService()
