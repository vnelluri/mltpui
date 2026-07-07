# Prompt: Multi-Tenant ML Model Training Platform

## Model
claude-fable-5

---

## System Prompt

You are a senior full-stack engineer and AWS solutions architect specializing in enterprise ML platforms. You write production-quality code with no placeholders or TODOs. Every file you produce is complete, runnable, and deployable as-is. You think carefully about security, multi-tenancy isolation, and regulated-industry compliance before writing a single line.

---

## User Prompt

Build a complete, production-ready **multi-tenant ML Model Training Platform** end-to-end. Deliver every file needed to build, containerize, and deploy the system. Do not omit any file. Do not use placeholder comments like "# implement this later". Every function must be fully implemented.

---

## 1. CONTEXT AND CONSTRAINTS

- **Deployment target**: AWS ECS (Fargate) only. No Lambda, no Step Functions, no SageMaker pipelines. No AWS-managed ML services except as launch targets from the portal (EMR Studio, SageMaker Studio).
- **Database**: DynamoDB only. No RDS, no Aurora.
- **Auth**: Azure Entra ID as the identity provider. OIDC/OAuth2 PKCE flow. **Tenancy and role are derived entirely from Entra ID group membership** — not from DynamoDB or manual assignment. The ID token contains a `groups` claim with the user's Entra group object IDs. The backend resolves these group OIDs against a `GroupMapping` table in DynamoDB that maps each group OID to `{role, tenantId}`. On every authenticated request, `get_current_user` performs this resolution and caches the result in DynamoDB as a `UserProfile`. The frontend decodes the `groups` claim from the MSAL ID token, calls `GET /auth/me` to get the resolved `{role, tenantId}`, and stores it in React context — no separate user-management API call needed at login.
- **Snowflake connectivity**: All Snowflake access uses OAuth. The platform acts as an OAuth client against Snowflake's OAuth integration (configured in Snowflake to trust Entra ID as the authorization server). The user's Entra access token is exchanged for a Snowflake OAuth token (via Snowflake's token endpoint using the `urn:ietf:params:oauth:grant-type:token-exchange` grant) by the backend service. This per-user Snowflake token is then used for all direct queries **and** passed as an encrypted, short-lived credential to EMR Serverless jobs and SageMaker Training Jobs at submit time, so those compute jobs query Snowflake under the submitting user's identity — not a shared service account.
- **Brand**: Use the logo files found in `./Truist` directory. Brand colors: Cold Purple `#A6A3E0`, Valhalla `#2E1A47`, White `#FFFFFF`. Typography: Inter for UI, JetBrains Mono for code/IDs.
- **Frontend**: React 18 + TypeScript + Vite + Tailwind CSS. All Tailwind classes must be present in the source (no runtime class generation).
- **Backend**: Python 3.12 + FastAPI. Async throughout. Pydantic v2 models.
- **No placeholders**: Every API endpoint, every DynamoDB operation, every React component must be fully implemented.
- **Local development**: The entire stack must run on a developer's laptop with a single `docker compose up` command. No real AWS credentials, no real Entra ID tenant, and no real EMR/SageMaker connections should be required to run and test the full application locally.

---

## 2. ROLES AND PERMISSIONS

Four roles. **Role and tenant are derived from Entra ID group membership** — the backend resolves the user's `groups` claim against the `GroupMapping` table on every request. The frontend reads the resolved role from `GET /auth/me` immediately after login and stores it in React context. Route guards and API dependencies enforce the role on every navigation and every endpoint. No manual role assignment UI is needed — role changes are made by moving a user between Entra groups.

### Platform Admin
- Onboard and manage tenants (create, suspend, reactivate)
- Create and manage all users across all tenants
- Assign users to tenants and roles
- View all jobs, experiments, models across all tenants
- Launch EMR Studio or SageMaker Studio for any tenant
- Access audit log for all activity

### Tenant Admin
- Manage users within their own tenant only
- Create, view, cancel jobs within their tenant
- View experiments and registered models within their tenant
- Configure tenant-level settings (compute quotas, allowed frameworks)
- Launch EMR Studio or SageMaker Studio scoped to their tenant
- View audit log scoped to their tenant

### Data Scientist
- Submit training jobs (EMR Serverless or SageMaker Training Job)
- View and compare experiments (MLflow-compatible metadata stored in DynamoDB)
- Register model versions from completed runs
- View models belonging to their tenant
- Launch their personal notebook environment (EMR Studio or SageMaker Studio)

### MRM (Model Risk Management / Governance)
- Read-only access to all models and experiments across all tenants
- Download model cards and audit reports
- Submit governance review decisions (approve / reject model versions)
- Cannot submit jobs or modify any resources

---

## 3. DATA MODEL (DynamoDB)

Design and implement all DynamoDB table definitions, GSIs, and access patterns. Use single-table design with a PK/SK pattern. Implement the following entities and all their access patterns:

### Entities

**Tenant**
- tenantId (PK), name, status (active/suspended), createdAt, createdBy
- emrApplicationId, sagemakerDomainId, s3BucketName, computeQuotaVcpuHours
- allowedFrameworks: list (pytorch, tensorflow, sklearn, xgboost)
- GSI: by status

**GroupMapping** ← new entity, managed by PlatformAdmin
- groupId (Entra group object ID, PK), role (PlatformAdmin/TenantAdmin/DataScientist/MRM), tenantId
- description (human-readable label e.g. "Risk Analytics Data Scientists"), createdAt, createdBy
- GSI: by tenantId, by role
- This table is the source of truth for tenancy and role. Adding/removing a user from an Entra group changes their access on next login with no application changes.

**UserProfile** ← resolved and cached by backend on first login, updated on subsequent logins
- userId (Entra OID, PK), email, name, tenantId, role (resolved from GroupMapping)
- status (active/inactive), createdAt, lastLoginAt, lastResolvedGroupId
- GSI: by tenantId, by email
- Note: if the user's groups change in Entra, the profile is re-resolved on their next authenticated request (the backend always re-validates group membership from the JWT, never trusts the cached role alone)

**TrainingJob**
- jobId, tenantId, userId, name, status (queued/running/succeeded/failed/cancelled)
- framework, entryPointScript, s3InputPath, s3OutputPath
- computeType (emr_serverless/sagemaker), emrJobRunId or sagemakerTrainingJobName
- hyperparameters: map, createdAt, startedAt, completedAt, durationSeconds
- instanceType, instanceCount, volumeSizeGb
- GSI: by tenantId+status, by userId

**Experiment**
- experimentId, tenantId, name, description, createdBy, createdAt, tags: map
- GSI: by tenantId

**ExperimentRun**
- runId, experimentId, tenantId, jobId, status, startTime, endTime
- params: map, metrics: map, tags: map, artifactUri
- GSI: by experimentId, by tenantId

**ModelVersion**
- modelId, tenantId, name, version (integer), stage (None/Staging/Production/Archived)
- runId, framework, artifactUri, description
- inputSchema: map, outputSchema: map
- hasExplainer (boolean), driftBaselineUri
- registeredAt, registeredBy, promotedAt, promotedBy
- GSI: by tenantId+stage, by name+version

**GovernanceReview**
- reviewId, modelId, tenantId, reviewedBy, decision (approved/rejected/pending)
- comments, conditions, reviewedAt, expiresAt
- GSI: by modelId, by tenantId

**AuditEvent**
- eventId, tenantId, userId, action, resourceType, resourceId
- timestamp, ipAddress, userAgent, details: map
- GSI: by tenantId+timestamp, by userId+timestamp

**NotebookSession**
- sessionId, userId, tenantId, sessionType (emr_studio/sagemaker_studio)
- presignedUrl, urlExpiresAt, createdAt, status
- GSI: by userId

**SnowflakeTokenCache** ← stores short-lived encrypted Snowflake OAuth tokens per user
- userId (PK), snowflakeToken (encrypted with AWS KMS), expiresAt, issuedAt
- tenantId, snowflakeUsername (the Snowflake username the token is valid for)
- TTL: set to `expiresAt` so DynamoDB auto-expires stale tokens
- Note: token is encrypted at rest using AWS KMS (or LocalStack KMS locally). The encryption key ARN is stored in config. The plaintext token is never logged.

---

## 4. BACKEND (FastAPI)

### Project structure
```
backend/
├── app/
│   ├── main.py
│   ├── config.py                    # pydantic-settings, all env vars
│   ├── dependencies.py              # get_current_user, require_role, get_db
│   ├── auth/
│   │   ├── oidc.py                  # Entra ID token validation (python-jose)
│   │   └── models.py                # TokenPayload, CurrentUser
│   ├── db/
│   │   ├── client.py                # boto3 DynamoDB resource, table helpers
│   │   ├── models.py                # all Pydantic DynamoDB entity models
│   │   └── repositories/
│   │       ├── tenant_repo.py
│   │       ├── user_repo.py
│   │       ├── job_repo.py
│   │       ├── experiment_repo.py
│   │       ├── model_repo.py
│   │       ├── governance_repo.py
│   │       ├── audit_repo.py
│   │       ├── notebook_repo.py
│   │       ├── group_mapping_repo.py    # CRUD GroupMapping; resolve groups→role+tenant
│   │       └── snowflake_token_repo.py  # store/retrieve encrypted Snowflake OAuth tokens
│   ├── routers/
│   │   ├── auth.py                  # /auth/me, /auth/token-info
│   │   ├── tenants.py               # CRUD tenants (PlatformAdmin only)
│   │   ├── users.py                 # CRUD users, role assignment
│   │   ├── jobs.py                  # submit, list, get, cancel training jobs
│   │   ├── experiments.py           # CRUD experiments and runs
│   │   ├── models.py                # register, list, promote, archive model versions
│   │   ├── governance.py            # MRM review endpoints
│   │   ├── notebooks.py             # launch EMR Studio / SageMaker Studio session
│   │   ├── snowflake.py             # Snowflake OAuth token exchange + data preview
│   │   ├── group_mappings.py        # PlatformAdmin CRUD for group→role+tenant mappings
│   │   ├── audit.py                 # query audit log
│   │   └── health.py
│   ├── services/
│   │   ├── job_service.py           # submit to EMR Serverless or SageMaker Training
│   │   ├── notebook_service.py      # generate presigned URLs for EMR/SageMaker Studio
│   │   ├── audit_service.py         # write audit events (called from all mutating routes)
│   │   ├── model_card_service.py    # generate model card JSON
│   │   ├── snowflake_service.py     # Snowflake OAuth token exchange + query execution
│   │   └── group_resolver_service.py # resolve Entra groups claim → (role, tenantId)
│   └── middleware/
│       ├── tenant_scope.py          # inject tenant context, enforce isolation
│       └── request_logging.py
├── Dockerfile
├── requirements.txt
└── scripts/
    ├── create_tables.py             # create all DynamoDB tables and GSIs
    └── seed_demo_data.py
```

### Requirements for each router

**`/auth`**
- `GET /auth/me` → Resolve the user's Entra groups claim against `GroupMapping` table and return `CurrentUser` (userId, email, name, role, tenantId, resolvedFromGroupId). On first call, also writes/updates the `UserProfile` record in DynamoDB. If no matching group is found, return 403 with message "No group mapping found. Contact your platform administrator."
- `GET /auth/token-info` → return decoded JWT claims including raw `groups` array (dev only, disabled in prod)
- `GET /auth/snowflake-token` → exchange the user's Entra access token for a Snowflake OAuth token using the RFC 8693 token-exchange grant. Store the encrypted token in `SnowflakeTokenCache`. Return `{snowflakeUsername, expiresAt}` — never return the raw token to the frontend. The encrypted token is retrieved server-side whenever needed.

**`/tenants`** (PlatformAdmin only)
- `POST /tenants` → create tenant, provision S3 bucket prefix, write audit event
- `GET /tenants` → list all tenants with pagination
- `GET /tenants/{id}` → get tenant detail
- `PUT /tenants/{id}` → update tenant settings
- `POST /tenants/{id}/suspend` → suspend tenant
- `POST /tenants/{id}/reactivate` → reactivate tenant
- `GET /tenants/{id}/metrics` → job count, active users, compute hours used

**`/users`**
- `POST /users` → invite user (PlatformAdmin or TenantAdmin scoped to their tenant)
- `GET /users` → list users (PlatformAdmin sees all; TenantAdmin sees own tenant)
- `GET /users/{id}` → get user
- `PUT /users/{id}/role` → change role
- `PUT /users/{id}/status` → activate/deactivate

**`/jobs`**
- `POST /jobs` → submit training job. Accepts: computeType, framework, entryPointScript, s3InputPath, hyperparameters, instanceType, instanceCount, snowflakeDatabase, snowflakeSchema, snowflakeWarehouse (optional — when provided, the job reads source data from Snowflake). When Snowflake fields are provided: (1) retrieve the user's cached Snowflake OAuth token from `SnowflakeTokenCache`, (2) encrypt it for transit using AWS KMS/Secrets Manager, (3) pass it to the EMR/SageMaker job as a secure environment variable or Secrets Manager reference so the job authenticates to Snowflake as the submitting user. The token is never written to logs, S3, or DynamoDB in plaintext. Calls job_service to dispatch to EMR Serverless or SageMaker. Writes audit event.
- `GET /jobs` → list jobs. PlatformAdmin sees all; TenantAdmin and DS see own tenant only. Filter by status, framework, computeType.
- `GET /jobs/{id}` → get job detail including live status polled from EMR/SageMaker
- `POST /jobs/{id}/cancel` → cancel running job
- `GET /jobs/{id}/logs` → return CloudWatch log stream URL (signed URL)

**`/experiments`**
- `POST /experiments` → create experiment
- `GET /experiments` → list experiments for tenant
- `GET /experiments/{id}` → get experiment with run count
- `POST /experiments/{id}/runs` → create run, link to jobId
- `GET /experiments/{id}/runs` → list runs with pagination, sortable by any metric
- `GET /experiments/{id}/runs/{runId}` → get run detail
- `PUT /experiments/{id}/runs/{runId}/metrics` → log metrics (called by training script)
- `PUT /experiments/{id}/runs/{runId}/params` → log params
- `PUT /experiments/{id}/runs/{runId}/tags` → set tags

**`/models`**
- `POST /models` → register model version from a run
- `GET /models` → list registered models. MRM sees all tenants. Others see own tenant.
- `GET /models/{name}/versions` → list versions for a model name
- `GET /models/{name}/versions/{ver}` → get version detail
- `PUT /models/{name}/versions/{ver}/stage` → transition stage (TenantAdmin/PlatformAdmin). Requires governance review in Production.
- `GET /models/{name}/versions/{ver}/card` → return generated model card JSON
- `POST /models/{name}/versions/{ver}/archive` → archive a version

**`/governance`** (MRM and PlatformAdmin)
- `GET /governance/reviews` → list all pending and completed reviews
- `POST /governance/reviews` → create review for a model version
- `PUT /governance/reviews/{id}` → submit decision (approved/rejected) with comments and conditions
- `GET /governance/reviews/{id}` → get review detail
- `GET /governance/export/{modelId}/{ver}` → export governance package (model card + audit trail) as JSON

**`/snowflake`**
- `GET /snowflake/status` → return whether the current user has a valid cached Snowflake OAuth token (`{connected: bool, snowflakeUsername: str|null, expiresAt: str|null}`). Frontend polls this to show "Connected to Snowflake as <username>" or a "Connect" button.
- `POST /snowflake/connect` → trigger OAuth token exchange: take the user's current Entra access token (from `Authorization` header), call Snowflake's token exchange endpoint, encrypt and store in `SnowflakeTokenCache`. Return `{snowflakeUsername, expiresAt}`.
- `POST /snowflake/disconnect` → delete the user's `SnowflakeTokenCache` entry.
- `POST /snowflake/query` → execute a read-only SQL query against Snowflake using the user's cached token. Body: `{sql: string, database: string, schema: string, warehouse: string, limit: int (max 1000)}`. Returns `{columns: string[], rows: any[][], rowCount: int, queryId: string}`. Used for data preview in the job submission wizard. Only SELECT statements are allowed (enforce server-side with a SQL parser check).
- `GET /snowflake/databases` → list accessible Snowflake databases for the current user using their cached token.
- `GET /snowflake/databases/{db}/schemas` → list schemas in a database.
- `GET /snowflake/databases/{db}/schemas/{schema}/tables` → list tables.
- `GET /snowflake/databases/{db}/schemas/{schema}/tables/{table}/preview` → return first 50 rows as `{columns, rows}`.

**`/group-mappings`** (PlatformAdmin only)
- `POST /group-mappings` → create a new group mapping. Body: `{groupId: string, role: string, tenantId: string, description: string}`. Writes audit event.
- `GET /group-mappings` → list all group mappings with pagination.
- `GET /group-mappings/{groupId}` → get mapping detail.
- `PUT /group-mappings/{groupId}` → update role or tenantId for a group. Writes audit event.
- `DELETE /group-mappings/{groupId}` → remove mapping (users in this group will lose access on next login). Requires confirmation. Writes audit event.

**`/notebooks`**
- `POST /notebooks/launch` → launch EMR Studio or SageMaker Studio session. Body: `{sessionType: "emr_studio"|"sagemaker_studio", tenantId}`. Returns presigned URL valid 1h. Calls notebook_service. Writes audit event.
- `GET /notebooks/sessions` → list active sessions for current user

**`/audit`**
- `GET /audit/events` → query audit events. PlatformAdmin sees all; TenantAdmin sees own tenant. Filter: userId, resourceType, action, dateRange. Paginated.

### Security requirements
- Every endpoint validates the JWT against Entra ID JWKS endpoint (cached, refreshed every 15 min) **when `AUTH_MODE=prod`**
- **When `AUTH_MODE=dev`**: skip JWT validation entirely. Instead, `get_current_user` reads `DEV_USER_ID`, `DEV_USER_EMAIL`, `DEV_USER_NAME`, `DEV_USER_ROLE`, `DEV_USER_TENANT_ID` from environment and returns a synthetic `CurrentUser`. The synthetic user is treated as having a matching `GroupMapping` entry — no DynamoDB group lookup is performed. The dev mode bypass must be gated by `AUTH_MODE == "dev"` — it must never activate in prod.
- **Group resolution on every request (prod mode)**: `get_current_user` extracts the `groups` claim from the validated JWT, queries `GroupMapping` for each group OID, and resolves to `{role, tenantId}`. If multiple matching group mappings exist (user is in multiple mapped groups), the highest-privilege role wins (PlatformAdmin > MRM > TenantAdmin > DataScientist). If no mapping is found, return 403.
- Tenant isolation enforced via middleware: non-PlatformAdmin requests are automatically scoped to `current_user.tenantId`; any attempt to access another tenant's resource returns 403
- All mutating operations write an AuditEvent
- DynamoDB operations use boto3 condition expressions to prevent cross-tenant reads at the data layer (not just middleware)
- **Snowflake token security**: Snowflake OAuth tokens in `SnowflakeTokenCache` are encrypted with AWS KMS before storage. The KMS key is tenant-specific (one key per tenant). When passing tokens to EMR/SageMaker jobs, store them in AWS Secrets Manager with a TTL matching the token expiry, pass only the secret ARN to the job, and delete the secret after the job completes or fails. Never pass plaintext tokens in environment variables, task definitions, or S3.
- **`/snowflake/query` endpoint**: enforce that only SELECT statements are permitted. Parse the SQL before execution using `sqlparse` library. Reject any statement containing DDL keywords (CREATE, DROP, ALTER, INSERT, UPDATE, DELETE, MERGE, TRUNCATE) even if nested. Enforce the row limit at the query level by wrapping in `SELECT * FROM (...) LIMIT {limit}`.

### Mock service behaviour (when `EMR_MOCK_MODE=true`, `SAGEMAKER_MOCK_MODE=true`, or `SNOWFLAKE_MOCK_MODE=true`)
- `job_service.py`: when `EMR_MOCK_MODE=true`, `submit_emr_job()` skips the real `emr-serverless` boto3 call and returns a fake `jobRunId` of the form `mock-jr-{uuid4}`. Job status polling in `GET /jobs/{id}` returns a synthetic status progression: queued → running (after 5s) → succeeded (after 30s), based on `createdAt` timestamp diff. Log stream URL returns a static mock URL.
- `job_service.py`: when `SAGEMAKER_MOCK_MODE=true`, `submit_sagemaker_job()` similarly returns `mock-smj-{uuid4}` and synthetic status.
- `notebook_service.py`: when `SAGEMAKER_MOCK_MODE=true`, `launch_sagemaker_studio()` returns `https://mock-studio.local/session/{uuid4}`. When `EMR_MOCK_MODE=true`, `launch_emr_studio()` returns `https://mock-emr.local/session/{uuid4}`.
- `snowflake_service.py`: when `SNOWFLAKE_MOCK_MODE=true`:
  - `exchange_token()` skips the real Snowflake token endpoint call and returns a fake token `mock-sf-token-{uuid4}` with expiry 1 hour from now.
  - `execute_query()` returns a mock result set with realistic column names and 10 rows of synthetic data whose types match the requested table schema (if known from mock schema below) or generic string/float columns.
  - `list_databases()` returns `["PROD_DB", "DEV_DB", "ANALYTICS_DB"]`.
  - `list_schemas(db)` returns `["PUBLIC", "ML_FEATURES", "RISK_MODELS", "FRAUD_DETECTION"]`.
  - `list_tables(db, schema)` returns `["TRANSACTION_FEATURES", "CUSTOMER_FEATURES", "MODEL_INPUT_DAILY"]` with mock column metadata.
  - `get_table_preview()` returns 10 synthetic rows.
  - When Snowflake mock mode is on and a job is submitted with Snowflake fields, `job_service` skips writing to Secrets Manager and passes a mock secret ARN `mock-secret-arn/{uuid4}` to the job.
- All mock responses must be structurally identical to real responses so the frontend works identically in both modes.

---

## 5. FRONTEND (React + TypeScript)

### Project structure
```
frontend/
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── auth/
│   │   ├── msalConfig.ts            # Entra ID PKCE config
│   │   ├── AuthContext.tsx          # MSAL provider + useAuth hook
│   │   ├── roles.ts                 # role types, parseTenantRole(), hasRole()
│   │   └── RequireAuth.tsx          # route guard component
│   ├── api/
│   │   ├── client.ts                # axios instance, Bearer token injection, retry
│   │   ├── tenants.ts
│   │   ├── users.ts
│   │   ├── jobs.ts
│   │   ├── experiments.ts
│   │   ├── models.ts
│   │   ├── governance.ts
│   │   ├── notebooks.ts
│   │   ├── snowflake.ts             # Snowflake connect/status/query/browse API calls
│   │   ├── groupMappings.ts         # PlatformAdmin group mapping CRUD
│   │   └── audit.ts
│   ├── components/
│   │   ├── layout/
│   │   │   ├── Layout.tsx           # sidebar + topbar shell
│   │   │   ├── Sidebar.tsx          # role-aware navigation
│   │   │   └── Topbar.tsx
│   │   ├── shared/
│   │   │   ├── StatusBadge.tsx
│   │   │   ├── DataTable.tsx        # sortable, paginated table
│   │   │   ├── ConfirmDialog.tsx
│   │   │   ├── EmptyState.tsx
│   │   │   ├── ErrorBoundary.tsx
│   │   │   └── LoadingSpinner.tsx
│   │   ├── jobs/
│   │   │   ├── JobSubmitForm.tsx     # multi-step form: compute type → framework → data source → resources → hyperparams → review
│   │   │   └── JobStatusBadge.tsx
│   │   └── snowflake/
│   │       ├── SnowflakeConnectBanner.tsx  # top-of-page banner: "Connected as <user>" or "Connect to Snowflake" button
│   │       ├── SnowflakeQueryEditor.tsx    # SQL editor with run button, results table, row count
│   │       └── SnowflakeTableBrowser.tsx   # tree: databases → schemas → tables; click table → preview
│   ├── pages/
│   │   ├── LoginPage.tsx            # Microsoft SSO button, role selector for demo
│   │   ├── UnauthorizedPage.tsx
│   │   ├── admin/
│   │   │   ├── AdminDashboard.tsx   # platform metrics, tenant health, recent activity
│   │   │   ├── TenantsPage.tsx      # tenant list + create tenant modal
│   │   │   ├── TenantDetailPage.tsx # users, jobs, settings for one tenant
│   │   │   ├── UsersPage.tsx        # all users across tenants (resolved from group mappings)
│   │   │   └── GroupMappingsPage.tsx # map Entra group OIDs → role + tenant
│   │   ├── tenant/
│   │   │   ├── TenantDashboard.tsx  # tenant metrics, recent jobs, quota usage bar
│   │   │   ├── TenantUsersPage.tsx
│   │   │   └── TenantSettingsPage.tsx
│   │   ├── workspace/
│   │   │   ├── ExperimentsPage.tsx  # experiment list + run comparison table
│   │   │   ├── ExperimentDetailPage.tsx  # runs table, metric charts (Recharts)
│   │   │   ├── JobsPage.tsx         # job list with live status polling
│   │   │   ├── SubmitJobPage.tsx     # step-by-step job submission wizard
│   │   │   ├── ModelsPage.tsx       # registered models, stage badges
│   │   │   └── NotebookPage.tsx     # launch EMR Studio / SageMaker Studio
│   │   ├── governance/
│   │   │   ├── GovernanceDashboard.tsx  # all models awaiting review
│   │   │   ├── ReviewQueuePage.tsx
│   │   │   └── ReviewDetailPage.tsx     # model card + submit decision form
│   │   ├── snowflake/
│   │   │   └── SnowflakePage.tsx     # connection status, table browser, query editor
│   │   └── audit/
│   │       └── AuditLogPage.tsx
│   ├── hooks/
│   │   ├── usePolling.ts            # poll a function every N seconds
│   │   ├── useTenantContext.ts      # current tenant from auth context
│   │   └── useSnowflake.ts          # Snowflake connection status, connect/disconnect, query
│   ├── types/
│   │   └── platform.ts              # all TypeScript interfaces matching backend Pydantic models
│   └── styles/
│       └── globals.css              # Tailwind directives + brand CSS variables
├── public/
│   └── truist-logo.svg              # reference from ./Truist directory
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.ts               # brand colors registered as Tailwind tokens
└── postcss.config.js
```

### UI/UX requirements

**Brand tokens** — register in `tailwind.config.ts`:
```
colors:
  brand:
    purple: '#A6A3E0'      # Cold Purple — primary accents, active nav, buttons
    valhalla: '#2E1A47'    # Valhalla — sidebar background, headings
    white: '#FFFFFF'
  bg:
    dark: '#0A0614'        # page background
    card: '#120D22'        # card background
    elevated: '#1A1230'    # elevated surfaces
  text:
    primary: '#F0EEFF'
    secondary: '#9B94C0'
    muted: '#5A5280'
```

**Sidebar**: Valhalla background, brand-purple active state, logo from `./Truist` directory at top. Role badge in user block at bottom.

**Login page**: Left panel — Valhalla gradient with grid pattern, logo from `./Truist`, platform tagline. Right panel — Microsoft SSO button (real MSAL popup in prod; role-selector demo panel for dev when `VITE_DEMO_MODE=true`). After login, the frontend calls `GET /auth/me` to fetch the resolved `{role, tenantId}`. If the response is 403 (no group mapping found), redirect to a dedicated "No Access" page explaining that the user's Entra group has not been mapped to any tenant or role, with instructions to contact their administrator.

**Snowflake connection banner** (`SnowflakeConnectBanner.tsx`): appears at the top of the SubmitJobPage and SnowflakePage. Shows one of three states:
- Connected: green dot + "Connected to Snowflake as `<snowflakeUsername>`" + "Expires in Xm" + Disconnect button
- Not connected: amber dot + "Not connected to Snowflake" + "Connect" button (triggers `POST /snowflake/connect`)
- Expired: red dot + "Snowflake session expired" + "Reconnect" button
The connection state is checked by `useSnowflake` hook which polls `GET /snowflake/status` every 60 seconds.

**Snowflake data source step in job wizard**: when the user reaches the "Data source" step, show the `SnowflakeConnectBanner`. If connected, show the `SnowflakeTableBrowser` to let them pick a database/schema/table. Selecting a table auto-fills the Snowflake fields (database, schema, table) in the job submission form. Show a preview of the first 10 rows of the selected table using `GET /snowflake/.../preview`. The user can also type a custom SQL query to override the full table read.

**Group Mappings page** (`GroupMappingsPage.tsx`, PlatformAdmin only): table of all group mappings with columns: Entra Group ID, Description, Role badge, Tenant, Created. Actions: add new mapping (modal with fields: Group Object ID, Role dropdown, Tenant dropdown, Description), edit, delete with confirmation. Include a helper note: "To find a group's Object ID: Azure Portal → Entra ID → Groups → select group → Overview → Object ID".

**Job submission wizard**: 7 steps:
1. Compute type (EMR Serverless or SageMaker Training) — visual cards with icons
2. Framework (pytorch/tensorflow/sklearn/xgboost) — visual cards
3. Data source — two options presented as tabs:
   - **Snowflake** (default): shows `SnowflakeConnectBanner`, then `SnowflakeTableBrowser` to pick database/schema/table + optional SQL override + row preview
   - **S3**: manual entry of input S3 path
4. Script (entry point S3 path, output S3 path)
5. Resources (instance type, count, volume size; for EMR: driver/executor memory, max executors)
6. Hyperparameters (dynamic key-value editor — add/remove rows)
7. Review and submit — shows all config including Snowflake connection details (username, database, schema, table) or S3 path, with warning if Snowflake token will expire before the estimated job completion time

**Experiment comparison**: Side-by-side table of runs, columns are param/metric names, sortable, highlight best value in each metric column.

**Notebook launcher**: Two large visual cards — EMR Studio and SageMaker Studio — with descriptions. Click → API call → display returned presigned URL in a new tab. Show active sessions list below.

**Governance review**: Model card viewer (rendered JSON → formatted sections). Approve / Reject buttons with required comment field. Conditions field (free text). Read-only for non-MRM roles.

**All pages must handle**: loading state, empty state, error state, pagination.

---

## 6. INFRASTRUCTURE (Docker + ECS)

### Deliverables

**`backend/Dockerfile`**
- Three-stage build:
  - `base`: `python:3.12-slim`, install system deps (curl for healthcheck), create non-root user `appuser`
  - `dev` (target used by docker-compose): installs all requirements including `watchfiles` for hot reload, sets `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]`
  - `prod` (default target, used for ECS): copies only app source, sets `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]`
- Health check: `curl -f http://localhost:8000/health || exit 1`
- Exposes port 8000
- Never runs as root

**`frontend/Dockerfile`**
- Three-stage build:
  - `base`: `node:20-alpine`, set workdir `/app`, copy `package*.json`, run `npm ci`
  - `dev` (target used by docker-compose): copies source, sets `CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]`. Hot reload works because the source directory is bind-mounted.
  - `build`: runs `npm run build`
  - `prod` (default target, used for ECS): `nginx:alpine`, copies `/app/dist` from build stage, includes `nginx.conf` for SPA routing (all non-API, non-asset paths → `index.html`)
- `nginx.conf` must be included in the Dockerfile output: SPA fallback, gzip enabled, cache headers for hashed assets
- Exposes port 3000 (dev) / 80 (prod)

**`docker-compose.yml`** (local development — full stack, zero real AWS required)

Services:
- **`localstack`**: `image: localstack/localstack:3`, `SERVICES=dynamodb,s3,sts,kms,secretsmanager`. Exposes port 4566. Health check: `curl -f http://localhost:4566/_localstack/health`. Named volume `localstack-data` for persistence across restarts so seeded data survives.
- **`dynamo-init`**: `image: amazon/aws-cli`, depends on localstack healthy. Runs `create_tables.py` then `seed_demo_data.py` against LocalStack. Runs once (`restart: on-failure`, exit 0 after success).
- **`backend`**: builds from `./backend/Dockerfile` with target `dev`. Mounts `./backend:/app` for hot reload. Runs `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`. Depends on localstack healthy. Exposes port 8000. Environment: `DYNAMODB_ENDPOINT_URL=http://localstack:4566`, `AUTH_MODE=dev`, `DEV_USER_ROLE=PlatformAdmin` (overridable), `SNOWFLAKE_MOCK_MODE=true`, `EMR_MOCK_MODE=true`, `SAGEMAKER_MOCK_MODE=true`, `KMS_ENDPOINT_URL=http://localstack:4566`, `SECRETS_MANAGER_ENDPOINT_URL=http://localstack:4566`.
- **`frontend`**: builds from `./frontend/Dockerfile` with target `dev`. Mounts `./frontend:/app`, `/app/node_modules` as anonymous volume to preserve installed packages. Runs `npm run dev -- --host`. Depends on backend. Exposes port 3000. Environment: `VITE_API_BASE_URL=http://localhost:8000`, `VITE_DEMO_MODE=true`.
- Network: all services on `ml-platform` bridge network.

**`.env.example`**
```
# ── Auth ──────────────────────────────────────────────────────────────────────
ENTRA_TENANT_ID=
ENTRA_CLIENT_ID=
ENTRA_AUDIENCE=api://ml-training-platform

# AUTH_MODE controls backend auth behaviour:
#   prod  → validate real Entra ID JWT (requires ENTRA_* vars above)
#   dev   → skip JWT validation; inject a synthetic user from DEV_USER_* vars below
AUTH_MODE=dev

# Synthetic user injected when AUTH_MODE=dev. Change to test different roles.
# Roles: PlatformAdmin | TenantAdmin | DataScientist | MRM
DEV_USER_ID=dev-user-001
DEV_USER_EMAIL=dev@local.test
DEV_USER_NAME=Dev User
DEV_USER_ROLE=PlatformAdmin
DEV_USER_TENANT_ID=tenant-risk-analytics   # ignored when role is PlatformAdmin

# ── AWS (real deployment) ─────────────────────────────────────────────────────
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=                         # leave blank when using instance profile in ECS
AWS_SECRET_ACCESS_KEY=

# ── DynamoDB ──────────────────────────────────────────────────────────────────
DYNAMODB_TABLE_NAME=ml-platform
# Set to LocalStack endpoint for local dev; leave blank for real AWS
DYNAMODB_ENDPOINT_URL=http://localstack:4566

# ── S3 ────────────────────────────────────────────────────────────────────────
S3_ENDPOINT_URL=http://localstack:4566     # leave blank for real AWS
S3_ARTIFACTS_BUCKET=ml-platform-artifacts

# ── EMR Serverless ────────────────────────────────────────────────────────────
EMR_SERVERLESS_APPLICATION_ID=
# When blank in dev mode, job submission returns a fake jobRunId instead of
# calling real EMR, so the full job creation flow can be tested locally.
EMR_MOCK_MODE=true

# ── SageMaker ─────────────────────────────────────────────────────────────────
SAGEMAKER_EXECUTION_ROLE_ARN=
SAGEMAKER_DOMAIN_ID=
# When true in dev mode, notebook launch returns a fake presigned URL.
SAGEMAKER_MOCK_MODE=true

# ── Snowflake OAuth ───────────────────────────────────────────────────────────
# Snowflake account identifier (e.g. myorg-myaccount or xy12345.us-east-1)
SNOWFLAKE_ACCOUNT=
# Snowflake OAuth integration name (created in Snowflake: CREATE SECURITY INTEGRATION ...)
SNOWFLAKE_OAUTH_INTEGRATION_NAME=ml_platform_oauth
# Snowflake token exchange endpoint (derived from account but made explicit for clarity)
# Format: https://<account>.snowflakecomputing.com/oauth/token-request
SNOWFLAKE_TOKEN_URL=
# Client ID and secret of the Snowflake OAuth integration
# (obtained from Snowflake: DESCRIBE SECURITY INTEGRATION ml_platform_oauth)
SNOWFLAKE_OAUTH_CLIENT_ID=
SNOWFLAKE_OAUTH_CLIENT_SECRET=
# Default warehouse to use for queries when user doesn't specify
SNOWFLAKE_DEFAULT_WAREHOUSE=COMPUTE_WH
# When true: skip real Snowflake calls; return mock data. Required for local dev.
SNOWFLAKE_MOCK_MODE=true

# ── KMS (Snowflake token encryption) ─────────────────────────────────────────
# AWS KMS key ARN used to encrypt Snowflake tokens at rest in DynamoDB
# In local dev with LocalStack, a mock key alias is used automatically
KMS_SNOWFLAKE_KEY_ARN=
# Set to http://localstack:4566 for local dev; leave blank for real AWS
KMS_ENDPOINT_URL=http://localstack:4566

# ── Secrets Manager (Snowflake token transit to EMR/SageMaker) ───────────────
SECRETS_MANAGER_ENDPOINT_URL=http://localstack:4566  # leave blank for real AWS
# Prefix for secrets created during job submission (auto-deleted after job ends)
SECRETS_MANAGER_JOB_TOKEN_PREFIX=ml-platform/job-tokens/

# ── Frontend ──────────────────────────────────────────────────────────────────
VITE_API_BASE_URL=http://localhost:8000
VITE_ENTRA_TENANT_ID=
VITE_ENTRA_CLIENT_ID=
# true  → show role-selector on login page, skip real MSAL popup
# false → use real Entra ID MSAL PKCE flow
VITE_DEMO_MODE=true
```

**`infrastructure/ecs/`**
- `task-definition-backend.json` — ECS task definition for backend. Memory 1024, CPU 512. Environment variables from SSM Parameter Store (referenced as `valueFrom`). Log driver: awslogs to CloudWatch.
- `task-definition-frontend.json` — ECS task definition for frontend. Memory 512, CPU 256.
- `ecs-service-backend.json` — ECS service definition. Desired count 2. Health check grace period 60s. Load balancer target group.
- `ecs-service-frontend.json` — ECS service definition.

**`infrastructure/dynamodb/`**
- `tables.json` — CloudFormation template creating all DynamoDB tables with GSIs, TTL where applicable, billing mode PAY_PER_REQUEST.

**`.env.example`**
```
# Entra ID
ENTRA_TENANT_ID=
ENTRA_CLIENT_ID=
ENTRA_AUDIENCE=api://ml-training-platform

# AWS
AWS_REGION=us-east-1
DYNAMODB_TABLE_NAME=ml-platform
DYNAMODB_ENDPOINT_URL=http://localstack:4566   # local only

# EMR
EMR_SERVERLESS_APPLICATION_ID=

# SageMaker
SAGEMAKER_EXECUTION_ROLE_ARN=
SAGEMAKER_DOMAIN_ID=

# Frontend
VITE_API_BASE_URL=http://localhost:8000
VITE_ENTRA_TENANT_ID=
VITE_ENTRA_CLIENT_ID=
VITE_DEMO_MODE=true
```

---

## 7. SCRIPTS

**`backend/scripts/create_tables.py`**
- Fully implemented Python script using boto3
- Reads `DYNAMODB_ENDPOINT_URL` from environment — defaults to `http://localhost:4566` if not set, so it works with LocalStack out of the box
- Creates the DynamoDB table with all GSIs as defined in section 3
- Idempotent: calls `describe_table`, skips creation if already exists, prints status
- Prints table ARN and GSI names on success
- Works against both LocalStack and real AWS (when `DYNAMODB_ENDPOINT_URL` is unset)

**`backend/scripts/seed_demo_data.py`**
- Reads same `DYNAMODB_ENDPOINT_URL` as above
- Idempotent: checks if data already exists before inserting (keyed on well-known IDs like `tenant-risk-analytics`). Running twice must not duplicate records.
- Creates 3 demo tenants: Risk Analytics, Fraud Detection, Compliance
- Creates 6 demo `GroupMapping` entries (one per role-tenant combination). Use well-known fake UUIDs as group OIDs so they are predictable in tests: e.g. `aaaaaaaa-0001-0001-0001-000000000001` for PlatformAdmin group, `aaaaaaaa-0002-0001-0001-000000000002` for Risk Analytics TenantAdmin group, etc.
- Creates 8 demo `UserProfile` entries: 1 PlatformAdmin, 1 MRM, 2 TenantAdmins (one per tenant except Compliance), 4 DataScientists distributed across tenants. Each UserProfile has `lastResolvedGroupId` set to the corresponding demo group OID.
- Creates 10 training jobs in various states (queued, running, succeeded ×5, failed ×2, cancelled)
- Creates 3 experiments with 8 runs each, with realistic metrics (AUC 0.85–0.97, F1 0.80–0.95, PSI 0.01–0.05, val_loss decreasing per epoch)
- Creates 6 model versions across stages (2× None, 2× Staging, 1× Production, 1× Archived)
- Creates 2 governance reviews (1 pending, 1 approved)
- Creates 15 audit events spanning the last 7 days
- Prints a summary table of what was created

**`backend/scripts/reset_local_db.py`**
- Deletes and recreates the DynamoDB table against LocalStack, then calls seed_demo_data
- Use when you want a clean slate during development
- Prints a confirmation prompt before deleting: `"This will delete all local data. Continue? [y/N]"`

**`backend/scripts/setup_snowflake_integration.sql`**
- A fully written Snowflake SQL script that a Snowflake ACCOUNTADMIN runs once to configure the OAuth integration
- Creates: `SECURITY INTEGRATION ml_platform_oauth` of type OAUTH with `OAUTH_CLIENT=CUSTOM`, `OAUTH_REDIRECT_URI` pointing at the platform's callback URL, and trusted Entra ID issuer
- Creates a dedicated `ML_PLATFORM_ROLE` in Snowflake with appropriate permissions
- Creates resource monitors and warehouse grants
- Includes `DESCRIBE SECURITY INTEGRATION ml_platform_oauth;` at the end to show the client ID and secret needed for `.env`
- Each statement is preceded by a comment explaining what it does and why

**`backend/scripts/setup_local_kms.py`**
- Creates a LocalStack KMS key and stores its ARN in `.env.local` (or prints it for manual copy)
- Creates a LocalStack Secrets Manager resource for testing job token transit
- Run automatically by `dev.sh` after LocalStack starts (before `create_tables.py`)
- Idempotent: checks if the key alias `alias/ml-platform-snowflake` already exists before creating

**`scripts/dev.sh`** (project root, executable)
```bash
#!/usr/bin/env bash
# One-command local dev setup. Run from project root.
```
- Checks prerequisites: Docker, docker compose, Python 3.12, Node 20. Prints clear error and exits if any are missing.
- Copies `.env.example` to `.env` if `.env` does not exist yet, and prints a notice.
- Runs `docker compose up --build -d`
- Waits for LocalStack health endpoint (`http://localhost:4566/_localstack/health`) with a 60-second timeout, printing dots while waiting
- Runs `setup_local_kms.py` to create the LocalStack KMS key and Secrets Manager resources
- Waits for backend health endpoint (`http://localhost:4566/_localstack/health`) with a 60-second timeout, printing dots while waiting.
- Waits for backend health endpoint (`http://localhost:8000/health`) with a 30-second timeout.
- Prints a summary:
  ```
  ✅ ML Training Platform is running locally

  Frontend:   http://localhost:3000
  Backend:    http://localhost:8000
  API docs:   http://localhost:8000/docs
  LocalStack: http://localhost:4566

  Demo credentials (AUTH_MODE=dev):
    Role:     PlatformAdmin  (change DEV_USER_ROLE in .env to switch)
    Tenants:  Risk Analytics · Fraud Detection · Compliance
    Users:    8 demo users seeded across 6 group mappings

  Snowflake (SNOWFLAKE_MOCK_MODE=true):
    All Snowflake calls return mock data — no real Snowflake account needed.
    Mock databases: PROD_DB · DEV_DB · ANALYTICS_DB
    Mock schema: ML_FEATURES with tables TRANSACTION_FEATURES · CUSTOMER_FEATURES

  To change your demo role:
    Edit DEV_USER_ROLE in .env, then: docker compose restart backend

  To reset demo data:
    docker compose exec backend python scripts/reset_local_db.py

  To stop:
    docker compose down
  ```

**`scripts/test-api.sh`** (project root, executable)
- A fully implemented shell script using `curl` and `jq` that smoke-tests every major API endpoint against the local backend
- Tests run in sequence; each prints PASS or FAIL with the HTTP status code
- Covers: health, GET /auth/me, POST /tenants, GET /tenants, POST /users, GET /users, POST /jobs, GET /jobs, POST /experiments, GET /experiments, POST /models, GET /models, GET /audit/events
- At the end prints a summary: `N/M tests passed`
- Requires `curl` and `jq` to be installed; prints installation instructions if missing

---

## 8. README

Write a complete `README.md` covering:

1. **Architecture diagram** (ASCII art showing: Browser → Frontend (ECS) → Backend (ECS) → DynamoDB, with LocalStack replacing DynamoDB/S3 in local dev, and EMR/SageMaker as optional external targets)

2. **Quick start — local dev (the most prominent section, at the top)**
   ```bash
   git clone <repo>
   cd ml-training-platform
   ./scripts/dev.sh        # handles everything: builds, starts, seeds, prints URLs
   ```
   Then: open http://localhost:3000 — you are already logged in as Platform Admin via `AUTH_MODE=dev`. No Entra ID setup needed.

3. **How local dev auth works**
   - Explain `AUTH_MODE=dev`: backend skips JWT validation and injects a synthetic user from `DEV_USER_*` env vars
   - Explain `VITE_DEMO_MODE=true`: frontend shows a role-selector dropdown on the login page instead of the Microsoft SSO button
   - Table showing which env vars to change to test each role:
     | Role | DEV_USER_ROLE | DEV_USER_TENANT_ID |
     |---|---|---|
     | Platform Admin | PlatformAdmin | (leave blank) |
     | Tenant Admin | TenantAdmin | tenant-risk-analytics |
     | Data Scientist | DataScientist | tenant-fraud-detection |
     | MRM | MRM | (leave blank) |
   - How to restart just the backend after changing a role: `docker compose restart backend`

4. **Prerequisites** (with version check commands)
   - Docker Desktop ≥ 24 / Docker Engine ≥ 24 + Docker Compose plugin: `docker --version && docker compose version`
   - `curl` and `jq` (for test-api.sh): `curl --version && jq --version`
   - AWS CLI (for ECS deployment only, not required locally): `aws --version`
   - No Python or Node needed locally — everything runs inside Docker

5. **Local development workflow**
   - Viewing logs: `docker compose logs -f backend`, `docker compose logs -f frontend`
   - Hot reload: backend reloads on any `.py` file save (uvicorn --reload + bind mount). Frontend reloads on any `.ts/.tsx` file save (Vite HMR).
   - Accessing the API interactively: http://localhost:8000/docs (FastAPI Swagger UI, fully functional with `AUTH_MODE=dev`)
   - Resetting data: `docker compose exec backend python scripts/reset_local_db.py`
   - Running the API smoke test suite: `./scripts/test-api.sh`
   - Stopping: `docker compose down`. Data persists in the `localstack-data` named volume.
   - Full clean (remove volumes too): `docker compose down -v`
   - Running backend tests: `docker compose exec backend pytest`
   - Running frontend type-check: `docker compose exec frontend npm run type-check`

6. **Switching between demo roles without restarting Docker**
   - Edit `DEV_USER_ROLE` (and `DEV_USER_TENANT_ID` if needed) in `.env`
   - Run `docker compose restart backend`
   - Hard-refresh the browser (Cmd+Shift+R)
   - The frontend role-selector dropdown on the login page is purely visual — it sets a `localStorage` key that the frontend reads to style the UI, but the actual role always comes from the backend synthetic user

7. **Entra ID App Registration setup** (for production only, not needed locally)
   - Exact step-by-step: no App Roles are used. Instead: Expose an API scopes (`ml-platform.read`, `ml-platform.write`). Token Configuration optional claims: `email`, `given_name`, `family_name`, `oid`, `tid`, `groups` (critical — this is the source of truth for role/tenant). Enable "Groups" in Token Configuration → Group Types to include: "Security groups". Note the group claim size limit (200 groups max in token — if users are in more, use Graph API overage claim handling in `oidc.py`).
   - **Group mapping setup**: after deploying, use `POST /group-mappings` (or `GroupMappingsPage` in the UI) to map each Entra security group OID to a role and tenant. Create Entra security groups like "ML-PlatformAdmins", "ML-RiskAnalytics-DataScientists", "ML-FraudDetection-TenantAdmins", etc. Add users to these groups to grant them access.

8. **Snowflake OAuth integration setup**
   - Run `backend/scripts/setup_snowflake_integration.sql` in Snowflake as ACCOUNTADMIN
   - Copy the client ID and secret from `DESCRIBE SECURITY INTEGRATION ml_platform_oauth` into your `.env`
   - Configure the Entra ID App Registration as a trusted identity provider in the Snowflake OAuth integration
   - Test by calling `POST /snowflake/connect` with a real Entra token — verify the returned `snowflakeUsername` matches the expected Entra UPN

9. **Moving from local dev to production** — the transition checklist:
   - [ ] Create real Entra ID App Registration with `groups` claim enabled
   - [ ] Set `AUTH_MODE=prod`, `VITE_DEMO_MODE=false`
   - [ ] Remove `DYNAMODB_ENDPOINT_URL`, `S3_ENDPOINT_URL`, `KMS_ENDPOINT_URL`, `SECRETS_MANAGER_ENDPOINT_URL`
   - [ ] Set `EMR_MOCK_MODE=false`, `SAGEMAKER_MOCK_MODE=false`, `SNOWFLAKE_MOCK_MODE=false`
   - [ ] Fill in `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_TOKEN_URL`, `SNOWFLAKE_OAUTH_CLIENT_ID`, `SNOWFLAKE_OAUTH_CLIENT_SECRET`
   - [ ] Create a real AWS KMS key and set `KMS_SNOWFLAKE_KEY_ARN`
   - [ ] Run `setup_local_kms.py` → replaced by real KMS key creation via AWS console or CDK
   - [ ] Run `setup_snowflake_integration.sql` in Snowflake
   - [ ] Fill in real `EMR_SERVERLESS_APPLICATION_ID`, `SAGEMAKER_DOMAIN_ID`, `SAGEMAKER_EXECUTION_ROLE_ARN`
   - [ ] Run `create_tables.py` against real AWS
   - [ ] Create group mappings via `GroupMappingsPage` or `POST /group-mappings` API
   - [ ] Add users to Entra security groups to grant them platform access

9. **AWS setup** (DynamoDB table creation, ECS cluster, IAM roles, ALB, ECR push)

10. **ECS deployment steps** (build → push ECR → register task def → update service)

11. **Environment variables reference** (full table: variable, description, local default, prod example)

12. **API usage examples** (curl against local backend with no auth headers needed in dev mode):
    - Create a tenant
    - List jobs
    - Submit a training job (EMR mock)
    - Register a model version
    - Submit a governance review

---

## 9. LOCAL DEVELOPMENT ENVIRONMENT SUMMARY

The complete local stack must be runnable with:
```bash
./scripts/dev.sh
```
and must provide:

| Capability | How it works locally |
|---|---|
| Authentication | `AUTH_MODE=dev` — backend injects synthetic user from env vars, no Entra ID needed |
| Group resolution | `AUTH_MODE=dev` — synthetic user has a pre-resolved role/tenantId; no `GroupMapping` lookup performed |
| Frontend auth UI | `VITE_DEMO_MODE=true` — role-selector dropdown replaces Microsoft SSO button |
| Snowflake | `SNOWFLAKE_MOCK_MODE=true` — all token exchange and queries return mock data |
| Snowflake token encryption | LocalStack KMS (`KMS_ENDPOINT_URL=http://localstack:4566`) — uses `alias/ml-platform-snowflake` created by `setup_local_kms.py` |
| Snowflake token transit to jobs | LocalStack Secrets Manager (`SECRETS_MANAGER_ENDPOINT_URL=http://localstack:4566`) — mock secret ARN returned, no real secret created |
| DynamoDB | LocalStack container at `http://localstack:4566` |
| S3 (artifact URIs) | LocalStack S3 at `http://localstack:4566`, bucket `ml-platform-artifacts` |
| EMR job submission | `EMR_MOCK_MODE=true` — returns fake job IDs, simulates status progression |
| SageMaker training | `SAGEMAKER_MOCK_MODE=true` — returns fake training job names |
| Notebook launch (EMR Studio) | Returns `https://mock-emr.local/session/{uuid}` |
| Notebook launch (SageMaker Studio) | Returns `https://mock-studio.local/session/{uuid}` |
| Demo data | Auto-seeded by `dynamo-init` container on first start |
| API documentation | FastAPI Swagger UI at `http://localhost:8000/docs` — all endpoints testable |
| Hot reload | Backend: uvicorn --reload. Frontend: Vite HMR |
| Smoke tests | `./scripts/test-api.sh` tests all major endpoints |

**Role switching during local dev** (no restart of full stack needed, just backend):
```bash
# Test as Data Scientist in Fraud Detection tenant
# Edit .env:  DEV_USER_ROLE=DataScientist  DEV_USER_TENANT_ID=tenant-fraud-detection
docker compose restart backend
# Refresh browser
```

---

## 10. OUTPUT FORMAT

Produce all files in this exact order:

1. `README.md`
2. `.env.example`
3. `docker-compose.yml`
4. `scripts/dev.sh`
5. `scripts/test-api.sh`
6. `backend/requirements.txt`
7. `backend/Dockerfile`
8. `backend/nginx.conf`
9. `backend/app/config.py`
10. `backend/app/main.py`
11. `backend/app/dependencies.py`
12. `backend/app/auth/oidc.py`
13. `backend/app/auth/models.py`
14. `backend/app/db/client.py`
15. `backend/app/db/models.py`
16. `backend/app/db/repositories/tenant_repo.py`
17. `backend/app/db/repositories/user_repo.py`
18. `backend/app/db/repositories/job_repo.py`
19. `backend/app/db/repositories/experiment_repo.py`
20. `backend/app/db/repositories/model_repo.py`
21. `backend/app/db/repositories/governance_repo.py`
22. `backend/app/db/repositories/audit_repo.py`
23. `backend/app/db/repositories/notebook_repo.py`
24. `backend/app/db/repositories/group_mapping_repo.py`
25. `backend/app/db/repositories/snowflake_token_repo.py`
26. `backend/app/services/job_service.py`
27. `backend/app/services/notebook_service.py`
28. `backend/app/services/audit_service.py`
29. `backend/app/services/model_card_service.py`
30. `backend/app/services/snowflake_service.py`
31. `backend/app/services/group_resolver_service.py`
32. `backend/app/middleware/tenant_scope.py`
33. `backend/app/middleware/request_logging.py`
34. `backend/app/routers/auth.py`
35. `backend/app/routers/tenants.py`
36. `backend/app/routers/users.py`
37. `backend/app/routers/jobs.py`
38. `backend/app/routers/experiments.py`
39. `backend/app/routers/models.py`
40. `backend/app/routers/governance.py`
41. `backend/app/routers/notebooks.py`
42. `backend/app/routers/snowflake.py`
43. `backend/app/routers/group_mappings.py`
44. `backend/app/routers/audit.py`
45. `backend/app/routers/health.py`
46. `backend/scripts/create_tables.py`
47. `backend/scripts/seed_demo_data.py`
48. `backend/scripts/reset_local_db.py`
49. `backend/scripts/setup_local_kms.py`
50. `backend/scripts/setup_snowflake_integration.sql`
51. `frontend/package.json`
52. `frontend/tsconfig.json`
53. `frontend/vite.config.ts`
54. `frontend/tailwind.config.ts`
55. `frontend/postcss.config.js`
56. `frontend/index.html`
57. `frontend/src/styles/globals.css`
58. `frontend/src/main.tsx`
59. `frontend/src/App.tsx`
60. `frontend/src/auth/msalConfig.ts`
61. `frontend/src/auth/AuthContext.tsx`
62. `frontend/src/auth/roles.ts`
63. `frontend/src/auth/RequireAuth.tsx`
64. `frontend/src/api/client.ts`
65. `frontend/src/api/tenants.ts`
66. `frontend/src/api/users.ts`
67. `frontend/src/api/jobs.ts`
68. `frontend/src/api/experiments.ts`
69. `frontend/src/api/models.ts`
70. `frontend/src/api/governance.ts`
71. `frontend/src/api/notebooks.ts`
72. `frontend/src/api/snowflake.ts`
73. `frontend/src/api/groupMappings.ts`
74. `frontend/src/api/audit.ts`
75. `frontend/src/types/platform.ts`
76. `frontend/src/hooks/usePolling.ts`
77. `frontend/src/hooks/useTenantContext.ts`
78. `frontend/src/hooks/useSnowflake.ts`
79. `frontend/src/components/layout/Layout.tsx`
80. `frontend/src/components/layout/Sidebar.tsx`
81. `frontend/src/components/layout/Topbar.tsx`
82. `frontend/src/components/shared/StatusBadge.tsx`
83. `frontend/src/components/shared/DataTable.tsx`
84. `frontend/src/components/shared/ConfirmDialog.tsx`
85. `frontend/src/components/shared/EmptyState.tsx`
86. `frontend/src/components/shared/ErrorBoundary.tsx`
87. `frontend/src/components/shared/LoadingSpinner.tsx`
88. `frontend/src/components/jobs/JobSubmitForm.tsx`
89. `frontend/src/components/jobs/JobStatusBadge.tsx`
90. `frontend/src/components/snowflake/SnowflakeConnectBanner.tsx`
91. `frontend/src/components/snowflake/SnowflakeQueryEditor.tsx`
92. `frontend/src/components/snowflake/SnowflakeTableBrowser.tsx`
93. `frontend/src/pages/LoginPage.tsx`
94. `frontend/src/pages/UnauthorizedPage.tsx`
95. `frontend/src/pages/NoAccessPage.tsx`
96. `frontend/src/pages/admin/AdminDashboard.tsx`
97. `frontend/src/pages/admin/TenantsPage.tsx`
98. `frontend/src/pages/admin/TenantDetailPage.tsx`
99. `frontend/src/pages/admin/UsersPage.tsx`
100. `frontend/src/pages/admin/GroupMappingsPage.tsx`
101. `frontend/src/pages/tenant/TenantDashboard.tsx`
102. `frontend/src/pages/tenant/TenantUsersPage.tsx`
103. `frontend/src/pages/tenant/TenantSettingsPage.tsx`
104. `frontend/src/pages/workspace/ExperimentsPage.tsx`
105. `frontend/src/pages/workspace/ExperimentDetailPage.tsx`
106. `frontend/src/pages/workspace/JobsPage.tsx`
107. `frontend/src/pages/workspace/SubmitJobPage.tsx`
108. `frontend/src/pages/workspace/ModelsPage.tsx`
109. `frontend/src/pages/workspace/NotebookPage.tsx`
110. `frontend/src/pages/snowflake/SnowflakePage.tsx`
111. `frontend/src/pages/governance/GovernanceDashboard.tsx`
112. `frontend/src/pages/governance/ReviewQueuePage.tsx`
113. `frontend/src/pages/governance/ReviewDetailPage.tsx`
114. `frontend/src/pages/audit/AuditLogPage.tsx`
115. `frontend/Dockerfile`
116. `infrastructure/ecs/task-definition-backend.json`
117. `infrastructure/ecs/task-definition-frontend.json`
118. `infrastructure/ecs/ecs-service-backend.json`
119. `infrastructure/ecs/ecs-service-frontend.json`
120. `infrastructure/dynamodb/tables.json`

For each file, output it as:
```
### FILE: path/to/file.ext
```
followed immediately by the complete file content in a code block.

Do not summarize. Do not skip any file. If a file is long, produce the full content anyway.

**Critical local dev requirements — verify before finishing:**
- [ ] `./scripts/dev.sh` starts the entire stack with zero manual steps, including LocalStack KMS setup
- [ ] `AUTH_MODE=dev` in `.env.example` means the backend works with no Entra ID configuration and no group resolution against DynamoDB
- [ ] `VITE_DEMO_MODE=true` in `.env.example` means the frontend shows a role-selector, not an SSO button
- [ ] `EMR_MOCK_MODE=true`, `SAGEMAKER_MOCK_MODE=true`, and `SNOWFLAKE_MOCK_MODE=true` mean all external service calls are mocked
- [ ] `docker-compose.yml` auto-seeds demo data (tenants, group mappings, user profiles, jobs, experiments) via the `dynamo-init` service
- [ ] `http://localhost:8000/docs` is a fully functional Swagger UI requiring no auth headers in dev mode; all Snowflake, group-mapping, and job endpoints are testable
- [ ] Changing `DEV_USER_ROLE` (and `DEV_USER_TENANT_ID`) in `.env` and running `docker compose restart backend` is the complete role-switching workflow
- [ ] `./scripts/test-api.sh` covers Snowflake mock endpoints, group mapping CRUD, and job submission with Snowflake data source
- [ ] The `SnowflakeConnectBanner` shows "Connected" state in demo mode without requiring a real Snowflake account
- [ ] Job submission with Snowflake data source works end-to-end in mock mode: token exchange → job submit → mock secret ARN → job status polling
