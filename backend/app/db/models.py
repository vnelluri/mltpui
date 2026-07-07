"""Pydantic v2 domain models for all DynamoDB entities.

These models represent the *domain* shape of each entity (clean field names,
no PK/SK). Repositories are responsible for mapping to/from the single-table
key structure. Key-building helpers live at the bottom of this module.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with ``Z`` suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ── Enums ────────────────────────────────────────────────────────────────────
class Role(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    MRM = "MRM"
    TENANT_ADMIN = "TenantAdmin"
    DATA_SCIENTIST = "DataScientist"


# Highest privilege first. Used to resolve multi-group membership.
ROLE_PRECEDENCE: List[str] = [
    Role.PLATFORM_ADMIN.value,
    Role.MRM.value,
    Role.TENANT_ADMIN.value,
    Role.DATA_SCIENTIST.value,
]


def highest_privilege_role(roles: List[str]) -> Optional[str]:
    """Return the highest-privilege role from a list, or None if empty."""
    for candidate in ROLE_PRECEDENCE:
        if candidate in roles:
            return candidate
    return None


class TenantStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class ProvisioningStatus(str, Enum):
    """Lifecycle of a tenant's dataplane resources (EMR Serverless app,
    execution role, S3 prefix, KMS key). Provisioned by the out-of-band IaC
    pipeline — the API only records the outcome via the write-back endpoint."""

    PENDING = "pending"
    ACTIVE = "active"
    FAILED = "failed"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ComputeType(str, Enum):
    EMR_SERVERLESS = "emr_serverless"
    SAGEMAKER = "sagemaker"


class Framework(str, Enum):
    PYTORCH = "pytorch"
    TENSORFLOW = "tensorflow"
    SKLEARN = "sklearn"
    XGBOOST = "xgboost"


class ModelStage(str, Enum):
    NONE = "None"
    STAGING = "Staging"
    PRODUCTION = "Production"
    ARCHIVED = "Archived"


class ReviewDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING = "pending"


class SessionType(str, Enum):
    EMR_STUDIO = "emr_studio"
    SAGEMAKER_STUDIO = "sagemaker_studio"


# ── Entity models ────────────────────────────────────────────────────────────
class Tenant(BaseModel):
    tenantId: str
    name: str
    status: str = TenantStatus.ACTIVE.value
    createdAt: str = Field(default_factory=utcnow_iso)
    createdBy: Optional[str] = None
    # Per-tenant dataplane resources, written back by the provisioning
    # pipeline (or filled with mock values in local dev). Job submission
    # fails loudly when these are missing in real (non-mock) mode.
    emrApplicationId: Optional[str] = None
    sagemakerDomainId: Optional[str] = None
    executionRoleArn: Optional[str] = None
    # Per-tenant Snowflake-token KMS key. Stored as an ARN because in the
    # control-plane/dataplane account split, KMS ALIASES do not resolve
    # across accounts — cross-account use requires the full key ARN (plus a
    # key policy granting the backend task role). Unset locally, where the
    # same-account alias convention still applies.
    kmsKeyArn: Optional[str] = None
    # Defaults to ACTIVE so tenant records written before this field existed
    # keep working; the create-tenant flow sets PENDING explicitly until the
    # provisioning pipeline reports back.
    provisioningStatus: str = ProvisioningStatus.ACTIVE.value
    s3BucketName: Optional[str] = None
    computeQuotaVcpuHours: int = 1000
    allowedFrameworks: List[str] = Field(
        default_factory=lambda: [
            Framework.PYTORCH.value,
            Framework.TENSORFLOW.value,
            Framework.SKLEARN.value,
            Framework.XGBOOST.value,
        ]
    )


class TrainingJob(BaseModel):
    jobId: str
    tenantId: str
    userId: str
    name: str
    status: str = JobStatus.QUEUED.value
    framework: str
    entryPointScript: str
    s3InputPath: Optional[str] = None
    s3OutputPath: Optional[str] = None
    computeType: str
    emrJobRunId: Optional[str] = None
    # The tenant's EMR Serverless application the run was submitted to,
    # captured at submit time so status polling / cancellation never needs
    # another tenant lookup (and keeps working if the tenant record changes).
    emrApplicationId: Optional[str] = None
    sagemakerTrainingJobName: Optional[str] = None
    hyperparameters: Dict[str, Any] = Field(default_factory=dict)
    createdAt: str = Field(default_factory=utcnow_iso)
    startedAt: Optional[str] = None
    completedAt: Optional[str] = None
    durationSeconds: Optional[int] = None
    instanceType: Optional[str] = None
    instanceCount: int = 1
    volumeSizeGb: int = 30
    snowflakeDatabase: Optional[str] = None
    snowflakeSchema: Optional[str] = None
    snowflakeWarehouse: Optional[str] = None
    snowflakeTable: Optional[str] = None
    snowflakeSql: Optional[str] = None
    snowflakeSecretArn: Optional[str] = None
    driverMemory: Optional[str] = None
    executorMemory: Optional[str] = None
    maxExecutors: Optional[int] = None
    # Every submitted job auto-creates a linked ExperimentRun (see routers/jobs.py)
    # so it always shows up as a comparison row in Experiments — these two fields
    # let job status updates propagate back to that run.
    experimentId: Optional[str] = None
    experimentRunId: Optional[str] = None


class Experiment(BaseModel):
    experimentId: str
    tenantId: str
    name: str
    description: Optional[str] = None
    createdBy: Optional[str] = None
    createdAt: str = Field(default_factory=utcnow_iso)
    tags: Dict[str, Any] = Field(default_factory=dict)


class ExperimentRun(BaseModel):
    runId: str
    experimentId: str
    tenantId: str
    jobId: Optional[str] = None
    status: str = JobStatus.RUNNING.value
    startTime: str = Field(default_factory=utcnow_iso)
    endTime: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    tags: Dict[str, Any] = Field(default_factory=dict)
    artifactUri: Optional[str] = None


class ModelVersion(BaseModel):
    modelId: str
    tenantId: str
    name: str
    version: int
    stage: str = ModelStage.NONE.value
    runId: Optional[str] = None
    framework: Optional[str] = None
    artifactUri: Optional[str] = None
    description: Optional[str] = None
    inputSchema: Dict[str, Any] = Field(default_factory=dict)
    outputSchema: Dict[str, Any] = Field(default_factory=dict)
    hasExplainer: bool = False
    driftBaselineUri: Optional[str] = None
    registeredAt: str = Field(default_factory=utcnow_iso)
    registeredBy: Optional[str] = None
    promotedAt: Optional[str] = None
    promotedBy: Optional[str] = None


class GovernanceReview(BaseModel):
    reviewId: str
    modelId: str
    tenantId: str
    modelName: Optional[str] = None
    modelVersion: Optional[int] = None
    # Who requested the review (DS/TenantAdmin) vs who decided it (MRM).
    submittedBy: Optional[str] = None
    reviewedBy: Optional[str] = None
    decision: str = ReviewDecision.PENDING.value
    comments: Optional[str] = None
    conditions: Optional[str] = None
    createdAt: str = Field(default_factory=utcnow_iso)
    reviewedAt: Optional[str] = None
    expiresAt: Optional[str] = None


class AuditEvent(BaseModel):
    eventId: str
    tenantId: Optional[str] = None
    userId: str
    action: str
    resourceType: str
    resourceId: Optional[str] = None
    timestamp: str = Field(default_factory=utcnow_iso)
    ipAddress: Optional[str] = None
    userAgent: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class NotebookSession(BaseModel):
    sessionId: str
    userId: str
    tenantId: Optional[str] = None
    sessionType: str
    # Returned ONCE in the launch response, never persisted — a presigned
    # URL is a credential; the stored record is metadata only (see
    # notebook_repo, which strips it on write).
    presignedUrl: Optional[str] = None
    urlExpiresAt: str
    createdAt: str = Field(default_factory=utcnow_iso)
    status: str = "active"


class RunToken(BaseModel):
    """Machine identity for one training run — see services/run_token_service.

    Only the SHA-256 hash of the opaque token is stored; the token itself
    travels to the compute job via the per-job Secrets Manager secret and is
    never persisted or returned by the API. Auto-expired by DynamoDB TTL.
    """

    tokenHash: str
    jobId: str
    experimentId: str
    runId: str
    tenantId: str
    createdAt: str = Field(default_factory=utcnow_iso)
    expiresAt: str


class SnowflakeTokenCache(BaseModel):
    userId: str
    snowflakeToken: str  # KMS-encrypted, base64 — never returned to clients
    expiresAt: str
    issuedAt: str = Field(default_factory=utcnow_iso)
    tenantId: Optional[str] = None
    snowflakeUsername: str


class FeatureView(BaseModel):
    """A named, reusable set of features — PREVIEW ONLY.

    This models the core Feast concept (an entity + a set of features tied
    to a source table) so the platform can demo "define features once, use
    them for both batch and real-time" without a real feature-store
    integration. The registry (this table) is real; the offline/online
    preview data returned by GET .../preview is entirely synthetic — see
    services/feature_store_service.py.
    """

    featureViewId: str
    tenantId: str
    name: str
    description: Optional[str] = None
    entityColumn: str
    features: List[Dict[str, str]] = Field(default_factory=list)  # [{"name","dtype"}]
    sourceTable: str
    experimentId: Optional[str] = None
    createdBy: Optional[str] = None
    createdAt: str = Field(default_factory=utcnow_iso)
    lastMaterializedAt: Optional[str] = None


# ── Single-table key builders ────────────────────────────────────────────────
def pad_version(version: int) -> str:
    """Zero-pad a model version so lexical ordering matches numeric ordering."""
    return f"{int(version):010d}"


class Keys:
    """Central definition of the single-table PK/SK/GSI structure.

    Each static method returns a dict of key attributes to merge into an item
    before ``put_item`` (write helpers) or the primary key for reads.
    """

    # Tenant --------------------------------------------------------------
    @staticmethod
    def tenant(tenant_id: str) -> Dict[str, str]:
        return {"PK": f"TENANT#{tenant_id}", "SK": f"TENANT#{tenant_id}"}

    @staticmethod
    def tenant_gsi(status: str, tenant_id: str) -> Dict[str, str]:
        return {"GSI1PK": f"TENANT_STATUS#{status}", "GSI1SK": f"TENANT#{tenant_id}"}

    # TrainingJob ---------------------------------------------------------
    @staticmethod
    def job(job_id: str) -> Dict[str, str]:
        return {"PK": f"JOB#{job_id}", "SK": f"JOB#{job_id}"}

    @staticmethod
    def job_gsi(tenant_id: str, status: str, user_id: str, created_at: str) -> Dict[str, str]:
        return {
            "GSI1PK": f"JOB_TENANT#{tenant_id}",
            "GSI1SK": f"STATUS#{status}#{created_at}",
            "GSI2PK": f"JOB_USER#{user_id}",
            "GSI2SK": f"JOB#{created_at}",
        }

    # Experiment ----------------------------------------------------------
    @staticmethod
    def experiment(experiment_id: str) -> Dict[str, str]:
        return {"PK": f"EXPERIMENT#{experiment_id}", "SK": "META"}

    @staticmethod
    def experiment_gsi(tenant_id: str, created_at: str, experiment_id: str) -> Dict[str, str]:
        return {
            "GSI1PK": f"EXP_TENANT#{tenant_id}",
            "GSI1SK": f"EXPERIMENT#{created_at}#{experiment_id}",
        }

    # ExperimentRun -------------------------------------------------------
    @staticmethod
    def run(experiment_id: str, run_id: str) -> Dict[str, str]:
        return {"PK": f"EXPERIMENT#{experiment_id}", "SK": f"RUN#{run_id}"}

    @staticmethod
    def run_gsi(tenant_id: str, run_id: str) -> Dict[str, str]:
        return {"GSI1PK": f"RUN_TENANT#{tenant_id}", "GSI1SK": f"RUN#{run_id}"}

    # ModelVersion --------------------------------------------------------
    # The tenant is part of the key: model names are namespaced PER TENANT,
    # so two tenants registering the same model name get independent
    # lineages instead of appending versions into each other's.
    @staticmethod
    def model_version(tenant_id: str, name: str, version: int) -> Dict[str, str]:
        return {
            "PK": f"MODEL#{tenant_id}#{name}",
            "SK": f"VERSION#{pad_version(version)}",
        }

    @staticmethod
    def model_version_gsi(tenant_id: str, stage: str, name: str, version: int, model_id: str) -> Dict[str, str]:
        return {
            "GSI1PK": f"MODEL_TENANT#{tenant_id}",
            "GSI1SK": f"STAGE#{stage}#{name}#{pad_version(version)}",
            "GSI2PK": f"MODELID#{model_id}",
            "GSI2SK": f"VERSION#{pad_version(version)}",
        }

    # GovernanceReview ----------------------------------------------------
    @staticmethod
    def review(review_id: str) -> Dict[str, str]:
        return {"PK": f"REVIEW#{review_id}", "SK": f"REVIEW#{review_id}"}

    @staticmethod
    def review_gsi(model_id: str, tenant_id: str, created_at: str, review_id: str) -> Dict[str, str]:
        return {
            "GSI1PK": f"REVIEW_MODEL#{model_id}",
            "GSI1SK": f"REVIEW#{created_at}#{review_id}",
            "GSI2PK": f"REVIEW_TENANT#{tenant_id}",
            "GSI2SK": f"REVIEW#{created_at}#{review_id}",
        }

    # AuditEvent ----------------------------------------------------------
    @staticmethod
    def audit(event_id: str) -> Dict[str, str]:
        return {"PK": f"AUDIT#{event_id}", "SK": f"AUDIT#{event_id}"}

    @staticmethod
    def audit_gsi(tenant_id: Optional[str], user_id: str, timestamp: str, event_id: str) -> Dict[str, str]:
        return {
            "GSI1PK": f"AUDIT_TENANT#{tenant_id or 'PLATFORM'}",
            "GSI1SK": f"{timestamp}#{event_id}",
            "GSI2PK": f"AUDIT_USER#{user_id}",
            "GSI2SK": f"{timestamp}#{event_id}",
        }

    # NotebookSession -----------------------------------------------------
    @staticmethod
    def notebook(session_id: str) -> Dict[str, str]:
        return {"PK": f"NOTEBOOK#{session_id}", "SK": f"NOTEBOOK#{session_id}"}

    @staticmethod
    def notebook_gsi(user_id: str, created_at: str, session_id: str) -> Dict[str, str]:
        return {"GSI1PK": f"NB_USER#{user_id}", "GSI1SK": f"{created_at}#{session_id}"}

    # SnowflakeTokenCache -------------------------------------------------
    @staticmethod
    def snowflake_token(user_id: str) -> Dict[str, str]:
        return {"PK": f"SFTOKEN#{user_id}", "SK": f"SFTOKEN#{user_id}"}

    # RunToken -------------------------------------------------------------
    @staticmethod
    def run_token(token_hash: str) -> Dict[str, str]:
        return {"PK": f"RUNTOKEN#{token_hash}", "SK": f"RUNTOKEN#{token_hash}"}

    # FeatureView -----------------------------------------------------------
    @staticmethod
    def feature_view(feature_view_id: str) -> Dict[str, str]:
        return {"PK": f"FEATUREVIEW#{feature_view_id}", "SK": f"FEATUREVIEW#{feature_view_id}"}

    @staticmethod
    def feature_view_gsi(tenant_id: str, created_at: str, feature_view_id: str) -> Dict[str, str]:
        return {
            "GSI1PK": f"FV_TENANT#{tenant_id}",
            "GSI1SK": f"FEATUREVIEW#{created_at}#{feature_view_id}",
        }
