// All TypeScript interfaces mirror the backend Pydantic models (camelCase JSON).

export type Role = 'PlatformAdmin' | 'TenantAdmin' | 'DataScientist' | 'MRM';

export type TenantStatus = 'active' | 'suspended';
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
export type ComputeType = 'emr_serverless' | 'sagemaker';
export type Framework = 'pytorch' | 'tensorflow' | 'sklearn' | 'xgboost';
export type ModelStage = 'None' | 'Staging' | 'Production' | 'Archived';
export type ReviewDecision = 'approved' | 'rejected' | 'pending';
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
  version: number;
  stage: ModelStage;
  runId: string;
  framework: Framework;
  artifactUri: string;
  description: string;
  inputSchema: Record<string, unknown>;
  outputSchema: Record<string, unknown>;
  hasExplainer: boolean;
  driftBaselineUri: string;
  registeredAt: string;
  registeredBy: string;
  promotedAt?: string | null;
  promotedBy?: string | null;
}

/** Mirrors backend build_model_card (services/model_card_service.py). */
export interface ModelCard {
  modelId: string;
  name: string;
  version: number;
  tenantId: string;
  stage: ModelStage;
  framework: string | null;
  description: string | null;
  artifactUri: string | null;
  registeredAt: string;
  registeredBy: string | null;
  promotedAt: string | null;
  promotedBy: string | null;
  schema: {
    input: Record<string, unknown>;
    output: Record<string, unknown>;
  };
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
  reviewedAt: string | null;
  expiresAt: string | null;
  modelName?: string;
  modelVersion?: number;
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
