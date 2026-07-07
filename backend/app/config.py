"""Application configuration via pydantic-settings.

All configuration is sourced from environment variables with sensible
defaults for local development (LocalStack + mock modes). Nothing here
requires real AWS, Entra ID, EMR, SageMaker or Snowflake to run locally.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import field_validator
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
    # Roles and tenants are DERIVED from Entra security-group NAMES — there is
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

    ENTRA_TENANT_ID: Optional[str] = None
    ENTRA_CLIENT_ID: Optional[str] = None
    # Client-credentials secret used ONLY for Microsoft Graph group-overage
    # lookups (users in >200 groups get no `groups` claim in their token).
    # Requires the GroupMember.Read.All application permission with admin
    # consent on the app registration.
    ENTRA_CLIENT_SECRET: Optional[str] = None
    ENTRA_AUDIENCE: str = "api://ml-training-platform"

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

    # ── SageMaker ───────────────────────────────────────────────────────────
    # Execution roles are per-tenant (Tenant.executionRoleArn) — there is
    # deliberately no platform-wide execution-role setting.
    SAGEMAKER_DOMAIN_ID: Optional[str] = None
    # Training container image used for SageMaker training jobs (platform-wide).
    SAGEMAKER_TRAINING_IMAGE: Optional[str] = None
    SAGEMAKER_MOCK_MODE: bool = True

    # ── Tenant provisioning (dataplane resources via IaC pipeline) ──────────
    # true (local dev): tenant creation self-provisions mock resource IDs and
    #   the tenant S3 prefix, and flips straight to provisioningStatus=active.
    # false (prod): tenant creation emits a TenantProvisioningRequested event
    #   to EventBridge; the IaC pipeline creates the EMR app / execution role /
    #   KMS key / S3 prefix in the dataplane account and reports back via
    #   PUT /tenants/{id}/provisioning.
    TENANT_PROVISIONING_MOCK_MODE: bool = True
    TENANT_PROVISIONING_EVENT_BUS: str = "default"

    # ── Snowflake OAuth ─────────────────────────────────────────────────────
    SNOWFLAKE_ACCOUNT: Optional[str] = None
    SNOWFLAKE_OAUTH_INTEGRATION_NAME: str = "ml_platform_oauth"
    SNOWFLAKE_TOKEN_URL: Optional[str] = None
    SNOWFLAKE_OAUTH_CLIENT_ID: Optional[str] = None
    SNOWFLAKE_OAUTH_CLIENT_SECRET: Optional[str] = None
    SNOWFLAKE_DEFAULT_WAREHOUSE: str = "COMPUTE_WH"
    # The Snowflake ROLE requested in the token-exchange scope
    # (session:role:<this>). Matches what setup_snowflake_integration.sql
    # creates and pre-authorizes — NOT the integration name.
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

    # ── Derived helpers ─────────────────────────────────────────────────────
    @property
    def is_dev_auth(self) -> bool:
        return self.AUTH_MODE == "dev"

    @property
    def jwks_url(self) -> Optional[str]:
        if not self.ENTRA_TENANT_ID:
            return None
        return (
            f"https://login.microsoftonline.com/"
            f"{self.ENTRA_TENANT_ID}/discovery/v2.0/keys"
        )

    @property
    def issuer(self) -> Optional[str]:
        if not self.ENTRA_TENANT_ID:
            return None
        return f"https://login.microsoftonline.com/{self.ENTRA_TENANT_ID}/v2.0"

    @property
    def snowflake_token_url(self) -> Optional[str]:
        if self.SNOWFLAKE_TOKEN_URL:
            return self.SNOWFLAKE_TOKEN_URL
        if self.SNOWFLAKE_ACCOUNT:
            return (
                f"https://{self.SNOWFLAKE_ACCOUNT}."
                f"snowflakecomputing.com/oauth/token-request"
            )
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


settings = get_settings()
