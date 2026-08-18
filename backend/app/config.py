"""Application configuration via pydantic-settings.

All configuration is sourced from environment variables with sensible
defaults for local development (LocalStack + mock modes). Nothing here
requires real AWS, Cognito, EMR, SageMaker or Snowflake to run locally.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Auth ────────────────────────────────────────────────────────────────
    AUTH_MODE: str = "dev"  # "dev" | "prod"
    DEV_USER_ID: str = "dev-user-001"
    DEV_USER_EMAIL: str = "dev@local.test"
    DEV_USER_NAME: str = "Dev User"
    DEV_USER_ROLE: str = "PlatformAdmin"
    DEV_USER_TENANT_ID: Optional[str] = "tenant-risk-analytics"
    # Optional comma-separated extra memberships for the dev user, each as
    # "Role:tenantId" (tenant blank for platform-wide roles) — lets the
    # membership switcher be exercised locally, e.g.
    # "DataScientist:tenant-risk-analytics,DataScientist:tenant-fraud-detection"
    DEV_USER_MEMBERSHIPS: str = ""

    # ── Group-name convention (source of truth for role/tenant) ─────────────
    # Roles and tenants are DERIVED from Azure AD security-group NAMES,
    # delivered in the Cognito ID token's custom:groups claim — there is
    # no mapping table to administer. Access is governed entirely by AD group
    # membership, which the firm's IGA process already reviews/recertifies.
    #
    # SECURITY PRECONDITION: creation of groups matching this convention must
    # be reserved to the governed provisioning process — with name-based
    # resolution, the group name IS the access grant.
    #
    # Tenant-scoped groups must match GROUP_NAME_PATTERN (case-insensitive)
    # with named captures `tenant` and `role`; the two platform-wide roles
    # use the fixed names below. Parsed tenants that don't exist as Tenant
    # records grant nothing.
    GROUP_NAME_PATTERN: str = (
        r"^myapp-(?P<tenant>[a-z0-9][a-z0-9-]*?)-(?P<role>datascientist|tenantadmin)$"
    )
    GROUP_NAME_PLATFORM_ADMIN: str = "myapp-platform-admin"
    GROUP_NAME_MRM: str = "myapp-platform-mrm"

    # ── Cognito (Azure AD SAML federation) ──────────────────────────────────
    # The frontend signs in via the Cognito Hosted UI (Amplify), which
    # federates to Azure AD over SAML. The backend validates the Cognito ID
    # token; user info (email, given_name) and Azure AD group names
    # (custom:groups, comma-separated) come from the SAML attribute mapping.
    COGNITO_USER_POOL_ID: Optional[str] = None
    # The app client ID — the expected `aud` of every ID token.
    COGNITO_APP_CLIENT_ID: Optional[str] = None
    # Region of the user pool; falls back to AWS_REGION when unset.
    COGNITO_REGION: Optional[str] = None

    # ── AWS ─────────────────────────────────────────────────────────────────
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None

    # ── DynamoDB ────────────────────────────────────────────────────────────
    DYNAMODB_TABLE_NAME: str = "ml-platform"
    DYNAMODB_ENDPOINT_URL: Optional[str] = None

    # ── S3 ──────────────────────────────────────────────────────────────────
    S3_ENDPOINT_URL: Optional[str] = None
    S3_ARTIFACTS_BUCKET: str = "ml-platform-artifacts"
    # true: model-registry artifact URIs are format-checked only — the S3
    # existence lookup (head/list) is skipped and the URI is trusted as-is.
    # Testing convenience; never enable in prod: the registry is what MRM
    # reviews against, so an unverified URI breaks the governance chain.
    ARTIFACT_URI_MOCK_MODE: bool = False

    # ── EMR Serverless ──────────────────────────────────────────────────────
    # Local-dev/mock default ONLY. In real mode every tenant has its own EMR
    # Serverless application (Tenant.emrApplicationId, written back by the
    # provisioning pipeline); job submission fails loudly if it is missing.
    # This value remains as a fallback for status-polling legacy job records
    # that predate per-tenant applications.
    EMR_SERVERLESS_APPLICATION_ID: Optional[str] = None
    # Separate from EMR_SERVERLESS_APPLICATION_ID: an EMR Studio is a distinct
    # AWS resource (the notebook workspace), provisioned out-of-band in
    # SSO/IAM-Identity-Center auth mode so each user's Entra identity flows
    # through natively (attributable notebook activity — no shared platform
    # identity, no presigned URLs). This is the Studio's access URL; the
    # platform only deep-links into it.
    # Known limitation: the Studio is platform-global while jobs are
    # per-tenant — acceptable for MVP because workspace S3 locations are
    # tenant-prefixed; per-tenant Studios are a later release.
    EMR_STUDIO_URL: Optional[str] = None
    EMR_MOCK_MODE: bool = True
    # EMR Studio authentication mode — a property of how the *Studio* is
    # configured, NOT a code branch: the backend deep-links the static
    # EMR_STUDIO_URL in both modes and AWS's hosted sign-in flow authenticates
    # the user. "IAM" (default): the access URL redirects to IAM sign-in / your
    # IdP (IAM federation); users need elasticmapreduce:CreateStudioPresignedUrl
    # on the Studio ARN so the hosted flow can presign them in. "SSO": Identity
    # Center supplies each user's Entra identity. See docs/EMR_STUDIO_IAM_MODE.md.
    # (CreateStudioPresignedUrl is not in the boto3 SDK; the app never calls it.)
    EMR_AUTH_MODE: str = "IAM"

    # ── SageMaker ───────────────────────────────────────────────────────────
    # Execution roles are per-tenant (Tenant.executionRoleArn) — there is
    # deliberately no platform-wide execution-role setting.
    # Platform-wide fallback SageMaker Studio domain; a tenant's own
    # sagemakerDomainId (Tenant record) takes precedence at launch. User
    # profiles are ensured lazily at first launch. For per-user CloudTrail
    # attribution, create the domain with
    # ExecutionRoleIdentityConfig=USER_PROFILE_NAME.
    SAGEMAKER_DOMAIN_ID: Optional[str] = None
    # Training container image used for SageMaker training jobs (platform-wide).
    SAGEMAKER_TRAINING_IMAGE: Optional[str] = None
    SAGEMAKER_MOCK_MODE: bool = True

    # ── Control-plane / dataplane account split ─────────────────────────────
    # Unset (default): single-account mode — the backend touches EMR
    # Serverless and job-token secrets with its own credentials (works for
    # local dev and a one-account MVP unchanged).
    # Set to the dataplane account's ml-platform-dataplane-runtime role ARN:
    # every EMR/job-secret call assumes it with a tenantId SESSION TAG, so
    # the dataplane's ABAC policy guarantees a request tagged for tenant A
    # cannot touch tenant B's application even if the backend has a bug.
    DATAPLANE_RUNTIME_ROLE_ARN: Optional[str] = None
    STS_ENDPOINT_URL: Optional[str] = None  # LocalStack/moto only

    # ── Tenant provisioning (direct boto3 into the dataplane) ───────────────
    # true (local dev): tenant creation self-provisions mock resource IDs and
    #   the tenant S3 prefix, and flips straight to provisioningStatus=active.
    # false (prod): tenant creation provisions the dataplane resources
    #   directly (KMS key, execution role, EMR Serverless app, S3 prefix)
    #   through the dataplane runtime role — see tenant_provisioning_service.
    #   Failures mark the tenant failed; POST /tenants/{id}/provision retries.
    TENANT_PROVISIONING_MOCK_MODE: bool = True
    # EMR Serverless release for newly provisioned tenant applications.
    EMR_RELEASE_LABEL: str = "emr-7.5.0"
    # Permissions boundary to attach to created tenant execution roles.
    # Orgs commonly allow runtime iam:CreateRole ONLY on the condition that
    # this boundary is attached — set it to the org's boundary ARN.
    TENANT_ROLE_PERMISSIONS_BOUNDARY_ARN: Optional[str] = None
    # Account split only: the backend task-role ARN, granted use of each
    # tenant KMS key in its key policy (the backend reaches KMS with its own
    # credentials cross-account — see dataplane_service docstring).
    BACKEND_PRINCIPAL_ARN: Optional[str] = None
    # CMK the artifacts bucket is SSE-encrypted with (account-baseline
    # output). Granted to each provisioned tenant execution role — without
    # it, jobs/notebooks cannot read or write the SSE-KMS bucket objects.
    # Blank in local dev (LocalStack bucket is unencrypted).
    S3_ARTIFACTS_KMS_KEY_ARN: Optional[str] = None

    # ── Snowflake OAuth ─────────────────────────────────────────────────────
    SNOWFLAKE_ACCOUNT: Optional[str] = None
    SNOWFLAKE_OAUTH_INTEGRATION_NAME: str = "ml_platform_oauth"
    # Entra tenant hosting our app client and the Snowflake app registration.
    # Snowflake tokens are minted at Entra (authorization-code + refresh
    # grants) and presented directly to Snowflake, whose External OAuth
    # integration trusts Entra as issuer — there is no Snowflake-side token
    # endpoint in this flow.
    ENTRA_TENANT_ID: Optional[str] = None
    # Our confidential app client in Entra (authorization-code + refresh).
    SNOWFLAKE_OAUTH_CLIENT_ID: Optional[str] = None
    SNOWFLAKE_OAUTH_CLIENT_SECRET: Optional[str] = None
    # Scope of the Snowflake app registration in Entra (e.g.
    # "api://<snowflake-app-uri>/session:scope:analyst") — appended to
    # "openid email offline_access" on the authorize/token requests. Snowflake
    # maps the resulting scp claim to the session role.
    SNOWFLAKE_OAUTH_SCOPE: Optional[str] = None
    SNOWFLAKE_DEFAULT_WAREHOUSE: str = "COMPUTE_WH"
    # Default Snowflake ROLE for platform sessions. With External OAuth the
    # active role comes from the Entra token's scp claim as mapped by
    # setup_snowflake_integration.sql — this names that pre-authorized role.
    SNOWFLAKE_DEFAULT_ROLE: str = "ML_PLATFORM_ROLE"
    # Minimum remaining validity a cached Snowflake token must have at job
    # submission: the job consumes it for the initial data read, so an
    # about-to-expire token fails fast here instead of mid-job.
    SNOWFLAKE_TOKEN_MIN_REMAINING_MINUTES: int = 10
    SNOWFLAKE_MOCK_MODE: bool = True

    # ── KMS (Snowflake token encryption) ────────────────────────────────────
    KMS_SNOWFLAKE_KEY_ARN: Optional[str] = None
    KMS_ENDPOINT_URL: Optional[str] = None

    # ── Secrets Manager (token transit to jobs) ─────────────────────────────
    SECRETS_MANAGER_ENDPOINT_URL: Optional[str] = None
    SECRETS_MANAGER_JOB_TOKEN_PREFIX: str = "ml-platform/job-tokens/"

    # ── Run tokens (machine identity for training jobs) ─────────────────────
    # Lifetime of the per-run API token minted at job submission — slightly
    # beyond the SageMaker MaxRuntimeInSeconds (24h) so a full-length job can
    # log final metrics.
    RUN_TOKEN_TTL_HOURS: int = 26
    # Public base URL of this API, injected into jobs as ML_PLATFORM_API_URL
    # so training code knows where to send metrics. Blank locally.
    PLATFORM_API_BASE_URL: Optional[str] = None

    # ── CORS ────────────────────────────────────────────────────────────────
    CORS_ALLOWED_ORIGINS: List[str] = ["http://localhost:3000"]

    @field_validator("CORS_ALLOWED_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v):
        """Allow comma-separated CORS origins in addition to JSON lists."""
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                return v  # let pydantic parse JSON
            return [o.strip() for o in stripped.split(",") if o.strip()]
        return v

    @field_validator("AUTH_MODE")
    @classmethod
    def _normalise_auth_mode(cls, v: str) -> str:
        value = (v or "dev").strip().lower()
        if value not in {"dev", "prod"}:
            raise ValueError("AUTH_MODE must be 'dev' or 'prod'")
        return value

    @field_validator("EMR_AUTH_MODE")
    @classmethod
    def _normalise_emr_auth_mode(cls, v: str) -> str:
        # Normalised for the iac/docs contract and any mode-specific reporting;
        # the launch path no longer branches on it (both modes deep-link
        # EMR_STUDIO_URL).
        value = (v or "IAM").strip().upper()
        if value not in {"SSO", "IAM"}:
            raise ValueError("EMR_AUTH_MODE must be 'SSO' or 'IAM'")
        return value

    # Every mock/bypass flag defaults to the local-dev value and env-var typos
    # are silently ignored (extra="ignore"), so a prod deployment missing one
    # variable would otherwise degrade SILENTLY: token audience/issuer checks
    # skipped, jobs fake-succeeding, artifact URIs unverified. Refuse to boot
    # instead — a crashed task in the ECS events is loud; a mock-mode prod is
    # invisible.
    @model_validator(mode="after")
    def _refuse_unsafe_prod_config(self) -> "Settings":
        if self.AUTH_MODE != "prod":
            return self
        problems = []
        if not self.COGNITO_USER_POOL_ID:
            problems.append(
                "COGNITO_USER_POOL_ID is not set (issuer verification would be skipped)"
            )
        if not self.COGNITO_APP_CLIENT_ID:
            problems.append(
                "COGNITO_APP_CLIENT_ID is not set (audience verification would be skipped)"
            )
        for flag in (
            "EMR_MOCK_MODE",
            "SAGEMAKER_MOCK_MODE",
            "SNOWFLAKE_MOCK_MODE",
            "TENANT_PROVISIONING_MOCK_MODE",
            "ARTIFACT_URI_MOCK_MODE",
        ):
            if getattr(self, flag):
                problems.append(f"{flag} is true")
        # Both auth modes deep-link the Studio access URL, so a missing
        # EMR_STUDIO_URL means notebook launch fails only when a user clicks —
        # check at boot like the flags above.
        if not self.EMR_STUDIO_URL:
            problems.append(
                "EMR_STUDIO_URL is not set (EMR Studio notebook launch would "
                "fail at click time)"
            )
        # Real-mode Snowflake mints tokens at Entra (authorization-code +
        # refresh); a missing app-client setting fails only when a user
        # connects — check at boot like the flags above.
        for name in (
            "ENTRA_TENANT_ID",
            "SNOWFLAKE_OAUTH_CLIENT_ID",
            "SNOWFLAKE_OAUTH_CLIENT_SECRET",
            "SNOWFLAKE_OAUTH_SCOPE",
            "SNOWFLAKE_ACCOUNT",
            # The OAuth redirect URI is derived from this — without it the
            # authorize URL cannot be built.
            "PLATFORM_API_BASE_URL",
        ):
            if not getattr(self, name):
                problems.append(
                    f"{name} is not set (Snowflake connect would fail at "
                    "click time)"
                )
        if problems:
            raise ValueError(
                "Refusing to start with AUTH_MODE=prod and an unsafe "
                "configuration: " + "; ".join(problems) + ". Set the missing "
                "variables (and every *_MOCK_MODE=false) explicitly, or use "
                "AUTH_MODE=dev for local development."
            )
        return self

    # ── Derived helpers ─────────────────────────────────────────────────────
    @property
    def is_dev_auth(self) -> bool:
        return self.AUTH_MODE == "dev"

    @property
    def cognito_region(self) -> str:
        return self.COGNITO_REGION or self.AWS_REGION

    @property
    def issuer(self) -> Optional[str]:
        if not self.COGNITO_USER_POOL_ID:
            return None
        return (
            f"https://cognito-idp.{self.cognito_region}.amazonaws.com/"
            f"{self.COGNITO_USER_POOL_ID}"
        )

    @property
    def jwks_url(self) -> Optional[str]:
        if not self.issuer:
            return None
        return f"{self.issuer}/.well-known/jwks.json"

    @property
    def entra_authorize_url(self) -> Optional[str]:
        if not self.ENTRA_TENANT_ID:
            return None
        return (
            f"https://login.microsoftonline.com/{self.ENTRA_TENANT_ID}"
            "/oauth2/v2.0/authorize"
        )

    @property
    def entra_token_url(self) -> Optional[str]:
        if not self.ENTRA_TENANT_ID:
            return None
        return (
            f"https://login.microsoftonline.com/{self.ENTRA_TENANT_ID}"
            "/oauth2/v2.0/token"
        )

    @property
    def snowflake_oauth_redirect_uri(self) -> Optional[str]:
        if not self.PLATFORM_API_BASE_URL:
            return None
        return self.PLATFORM_API_BASE_URL.rstrip("/") + "/snowflake/oauth/callback"

    @property
    def frontend_base_url(self) -> Optional[str]:
        # By convention the first CORS origin is the SPA — used as the
        # post-OAuth-callback redirect target.
        return self.CORS_ALLOWED_ORIGINS[0] if self.CORS_ALLOWED_ORIGINS else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


settings = get_settings()
