// All TypeScript interfaces mirror the backend Pydantic models (camelCase JSON).

export type Role = 'PlatformAdmin' | 'TenantAdmin' | 'DataScientist' | 'MRM';

export type TenantStatus = 'active' | 'suspended';
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
export type ComputeType = 'emr_serverless' | 'sagemaker';
export type Framework = 'pytorch' | 'tensorflow' | 'sklearn' | 'xgboost';
export type ModelStage = 'None' | 'Staging' | 'Production' | 'Archived';
export type ReviewDecision = 'approved' | 'rejected' | 'pending';
/** Derived development-journey status, computed by the backend model listing
 * (see routers/models.py::compute_dev_status) — never stored. */
export type ModelDevStatus =
  | 'initiated'
  | 'dev_complete'
  | 'submitted_to_mrm'
  | 'mrm_approved'
  | 'mrm_rejected';
export type SessionType = 'emr_studio' | 'sagemaker_studio';
export type NotebookStatus = 'active' | 'expired';
// Mirrors JobStatus — every run's status is synced from the job that
// produced it (see backend routers/jobs.py::_sync_run_with_job).
export type RunStatus = JobStatus;

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

export type ProvisioningStatus = 'pending' | 'active' | 'failed';

export interface Tenant {
  tenantId: string;
  name: string;
  status: TenantStatus;
  createdAt: string;
  createdBy: string;
  emrApplicationId: string;
  sagemakerDomainId: string;
  executionRoleArn?: string;
  provisioningStatus?: ProvisioningStatus;
  s3BucketName: string;
  computeQuotaVcpuHours: number;
  allowedFrameworks: Framework[];
}

/** Phase-1 cluster stats for a tenant's EMR Serverless application: job
 * counts from the platform DB, application state/max capacity from EMR, and
 * an ESTIMATED utilization (running jobs' executor demand — CloudWatch-backed
 * real utilization is a later phase). */
export interface TenantComputeStats {
  tenantId: string;
  applicationId: string | null;
  applicationState: string;
  runningJobs: number;
  queuedJobs: number;
  maxVcpu: number | null;
  allocatedVcpuEstimate: number;
  utilizationPct: number | null;
  estimated: boolean;
}

export interface TenantMetrics {
  tenantId: string;
  jobCount: number;
  computeHoursUsed: number;
  computeQuotaVcpuHours: number;
  runningJobs: number;
  registeredModels: number;
}

/** One (role, tenant) pair derived from a convention-named AD group. */
export interface Membership {
  role: Role;
  tenantId: string | null;
  /** Display name from the Tenant record (enriched by /auth/me). */
  tenantName: string | null;
  groupName: string | null;
}

export interface CurrentUser {
  userId: string;
  email: string;
  name: string;
  /** ACTIVE role — selected from memberships via the X-Active-* headers. */
  role: Role;
  /** ACTIVE tenant. */
  tenantId: string | null;
  /** Everything the user's AD groups grant; switchable in the topbar. */
  memberships: Membership[];
  resolvedFromGroupId: string | null;
}

export interface TrainingJob {
  jobId: string;
  tenantId: string;
  userId: string;
  name: string;
  status: JobStatus;
  /** Why the job is in its current state (failure reason, cancellation). */
  statusReason?: string | null;
  /** Data snapshot date (YYYY-MM-DD) the run trains on — AS_OF_DATE in the
   * script; clone with a different date to backfill. */
  asOfDate?: string | null;
  framework: Framework;
  entryPointScript: string;
  s3InputPath: string;
  s3OutputPath: string;
  computeType: ComputeType;
  emrJobRunId?: string | null;
  sagemakerTrainingJobName?: string | null;
  hyperparameters: Record<string, string>;
  createdAt: string;
  startedAt?: string | null;
  completedAt?: string | null;
  durationSeconds?: number | null;
  instanceType: string;
  instanceCount: number;
  volumeSizeGb: number;
  snowflakeDatabase?: string | null;
  snowflakeSchema?: string | null;
  snowflakeWarehouse?: string | null;
  snowflakeTable?: string | null;
  snowflakeSql?: string | null;
  driverMemory?: string | null;
  executorMemory?: string | null;
  maxExecutors?: number | null;
  /** Every submitted job auto-creates a linked ExperimentRun — see the
   * backend's routers/jobs.py::submit_job / _sync_run_with_job. */
  experimentId?: string | null;
  experimentRunId?: string | null;
}

export interface Experiment {
  experimentId: string;
  tenantId: string;
  name: string;
  description: string;
  createdBy: string;
  createdAt: string;
  tags: Record<string, string>;
  runCount?: number;
}

export interface ExperimentRun {
  runId: string;
  experimentId: string;
  tenantId: string;
  jobId: string;
  status: RunStatus;
  startTime: string;
  endTime: string | null;
  params: Record<string, string | number>;
  metrics: Record<string, number>;
  tags: Record<string, string>;
  artifactUri: string;
}

export interface ModelVersion {
  modelId: string;
  tenantId: string;
  name: string;
  version: string;
  stage: ModelStage;
  /** Business use case the model was registered against (required at
   * registration; may be absent on records that predate the field). */
  usecaseId?: string | null;
  /** Present on list responses only — derived from the version + its
   * governance reviews at read time. */
  devStatus?: ModelDevStatus;
  runId: string;
  framework: Framework;
  artifactUri: string;
  description: string;
  /** Single free-form I/O contract document (replaces input/output schemas). */
  modelSchema: Record<string, unknown>;
  /** Evaluation results submitted with the artifact — reviewed by MRM. */
  results: Record<string, unknown>;
  /** S3 URI of the model documentation package. */
  documentationUri?: string | null;
  hasExplainer: boolean;
  driftBaselineUri: string;
  registeredAt: string;
  registeredBy: string;
  promotedAt?: string | null;
  promotedBy?: string | null;
  /** ServiceNow change ticket recorded on promotion to Production. */
  snowTicketId?: string | null;
}

/** Mirrors backend build_model_card (services/model_card_service.py). */
export interface ModelCard {
  modelId: string;
  name: string;
  version: string;
  tenantId: string;
  stage: ModelStage;
  usecaseId: string | null;
  framework: string | null;
  description: string | null;
  artifactUri: string | null;
  registeredAt: string;
  registeredBy: string | null;
  promotedAt: string | null;
  promotedBy: string | null;
  snowTicketId: string | null;
  schema: Record<string, unknown>;
  results: Record<string, unknown>;
  documentationUri: string | null;
  explainability: {
    hasExplainer: boolean;
    driftBaselineUri: string | null;
  };
  trainingRun: {
    runId: string;
    experimentId: string;
    jobId: string | null;
    status: string;
    params: Record<string, unknown>;
    metrics: Record<string, unknown>;
    tags: Record<string, unknown>;
    artifactUri: string | null;
  } | null;
  governance: {
    reviewCount: number;
    hasApprovedReview: boolean;
    reviews: Record<string, unknown>[];
  };
}

export interface GovernanceReview {
  reviewId: string;
  modelId: string;
  tenantId: string;
  /** Who requested the review (DS/TenantAdmin); MRM sets reviewedBy on decision. */
  submittedBy?: string | null;
  reviewedBy: string;
  decision: ReviewDecision;
  comments: string;
  conditions: string;
  /** Artifacts MRM attaches alongside the decision (reports, evidence, memos). */
  mrmArtifactUris?: string[];
  createdAt?: string;
  reviewedAt: string | null;
  expiresAt: string | null;
  modelName?: string;
  modelVersion?: string;
}

export interface AuditEvent {
  eventId: string;
  tenantId: string;
  userId: string;
  action: string;
  resourceType: string;
  resourceId: string;
  timestamp: string;
  ipAddress: string;
  userAgent: string;
  details: Record<string, unknown>;
}

export interface NotebookSession {
  sessionId: string;
  userId: string;
  tenantId: string;
  sessionType: SessionType;
  /** Set when launched in collaborative mode for a business use case. */
  usecaseId?: string | null;
  /** Present only in the launch response — never persisted or re-listed. */
  presignedUrl: string | null;
  urlExpiresAt: string;
  createdAt: string;
  status: NotebookStatus;
}

// ── Snowflake ──────────────────────────────────────────────────────────────
export interface SnowflakeStatus {
  connected: boolean;
  snowflakeUsername: string | null;
  expiresAt: string | null;
}

export interface SnowflakeQueryResult {
  columns: string[];
  rows: unknown[][];
  rowCount: number;
  queryId: string;
}

export interface SnowflakeTableColumn {
  name: string;
  type: string;
}

export interface SnowflakePreview {
  columns: string[];
  rows: unknown[][];
}

// ── S3 ─────────────────────────────────────────────────────────────────────
export interface S3File {
  key: string;
  size: number;
  lastModified: string;
}

export interface S3BrowseResult {
  bucket: string;
  prefix: string;
  folders: string[];
  files: S3File[];
}

// ── Feature Store (preview) ─────────────────────────────────────────────────
// PREVIEW ONLY — no real feature-store integration. The FeatureView registry
// is real; batch/online preview data is synthetic (see backend
// services/feature_store_service.py).
export type FeatureDtype = 'string' | 'int64' | 'float' | 'bool' | 'timestamp';

export interface FeatureDefinition {
  name: string;
  dtype: FeatureDtype;
}

export interface FeatureView {
  featureViewId: string;
  tenantId: string;
  name: string;
  description: string | null;
  entityColumn: string;
  features: FeatureDefinition[];
  sourceTable: string;
  experimentId: string | null;
  createdBy: string;
  createdAt: string;
  lastMaterializedAt: string | null;
}

export interface FeatureOfflinePreview {
  columns: string[];
  rows: unknown[][];
}

export interface FeatureOnlinePreview {
  entityId: string;
  asOf: string;
  latencyMs: number;
  values: Record<string, unknown>;
}

export interface FeatureViewPreview {
  offline: FeatureOfflinePreview;
  online: FeatureOnlinePreview;
}
