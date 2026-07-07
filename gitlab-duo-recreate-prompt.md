# Prompt: Multi-Tenant ML Training Platform (GitLab Duo edition)

## How to use this document

This spec was written after actually building and running the full platform
end-to-end (Docker stack up, seed data verified, smoke tests passing). It
corrects several real bugs found during that build — see **§0 Corrections**
before you start, even if you're already familiar with the original spec.

**If you're using GitLab Duo Chat** (conversational, no autonomous multi-file
repo execution): work through this document top-to-bottom as a sequence of
separate chat turns, roughly one per numbered section (§4 is big — split it
per subsection: config → auth → db → repositories → services → routers →
main.py). After each turn, review the output before pasting the next prompt.
Do the same file-by-file for §5 (frontend).

**If you're using GitLab Duo Workflow / an agentic mode** that can plan and
write multiple files against a repo: paste this whole document as one task.
Explicitly ask it to verify itself at the end (§10) by running
`docker compose up --build -d` and the smoke test script, and to iterate
until both succeed — don't accept "should work" without that check.

Either way: **you must actually run `docker compose up` and
`scripts/test-api.sh` yourself and look at the output.** No AI-authored
codebase this size is trustworthy until it's been started and exercised.

---

## 0. Corrections vs. a naive first pass

These are real bugs hit while building this exact system. Bake the fixes in
from the start rather than rediscovering them:

1. **Pagination envelope must be consistent on every list endpoint, no
   exceptions.** Every `GET` that returns a collection — including
   `/notebooks/sessions` and `/models/{name}/versions`, which are easy to
   forget — must return `{items: T[], total: number, page: number,
   pageSize: number}`, never a bare array. A single endpoint returning a
   raw array while the frontend's shared API layer assumes the envelope
   causes an "Cannot read properties of undefined (reading 'length')"
   crash. Grep your own output for `-> List[` / `-> list[` in every router
   before considering it done — any hit is very likely this bug.

2. **"Sees all tenants" must not also require `tenantId is None`.** A role
   like MRM (or Platform Admin) that's supposed to see across every tenant
   needs a `sees_all_tenants` check that stands alone. Writing
   `if user.sees_all_tenants and user.tenantId is None:` is a trap: in dev
   mode, if a synthetic/test user happens to carry a non-null tenantId
   (e.g. because a shared `DEV_USER_TENANT_ID` env var is set), an MRM or
   Platform Admin user silently gets scoped to one tenant instead of all of
   them. Fix at the root: the dev-mode synthetic user constructor must null
   out `tenantId` for **every** role whose permission model says "sees all
   tenants" (Platform Admin AND MRM), not just Platform Admin. And list
   endpoints should check `sees_all_tenants` alone.

3. **EMR Serverless Application ID and EMR Studio ID are different AWS
   resources — don't reuse one config var for both.** EMR Serverless
   (`EMR_SERVERLESS_APPLICATION_ID`) is used for job submission. EMR Studio
   (needs its own `EMR_STUDIO_ID`) is a separate notebook-workspace
   resource used only for requesting a presigned login URL — this platform
   never creates an EMR Studio, it must be provisioned out-of-band, and the
   ID that points at it must be its own config variable.

4. **S3 browsing is a first-class feature, not an afterthought.** The
   original design only exposed S3 as a name-entry text field. Build a real
   `GET /s3/browse?prefix=` endpoint against the shared artifacts bucket
   (works against LocalStack with no mock mode needed — LocalStack
   genuinely emulates S3), scoped so non-admins can't browse outside
   `{tenantId}/`, and a folder-navigation UI component for the job
   submission wizard's S3 tab (mirroring the Snowflake table browser's
   UX — browse, select, with a manual-path override field kept for
   flexibility).

5. **Decide explicitly whether submitting a job auto-creates an
   ExperimentRun, and document the decision.** A `TrainingJob` (compute
   execution: status, EMR/SageMaker IDs, resource sizing) and an
   `ExperimentRun` (ML bookkeeping: params/metrics/artifactUri for
   comparison) are different concerns and must stay different tables/rows —
   but leaving them completely unlinked by default means jobs never show up
   in experiment comparisons unless the training script itself calls back
   into `PUT /experiments/{id}/runs/{runId}/metrics`. Recommended: have
   `POST /jobs` auto-create a linked `ExperimentRun` (status mirrors the
   job) so there's always a comparison row, and let the training script
   enrich it with real metrics/params as it runs.

6. **`docker compose restart` does not re-read `.env`.** It restarts the
   existing container with whatever environment was baked in at creation
   time. Changing a role-switch variable like `DEV_USER_ROLE` in `.env` and
   expecting it to take effect requires `docker compose up -d <service>`
   (recreates the container), not `restart`. Get this right in the README's
   role-switching instructions — it's the kind of thing that looks like a
   bug in the app when it's actually a compose-usage mistake.

7. **`npm ci` requires an existing lockfile.** Either commit a
   `package-lock.json` alongside `package.json` up front, or use
   `npm install` in the Dockerfile if you won't maintain a lockfile.
   Generate the lockfile once during your own build-and-verify pass
   (`npm install --package-lock-only`) rather than shipping a Dockerfile
   that fails on a clean checkout.

8. **Add `.dockerignore` to both `backend/` and `frontend/`** excluding
   `node_modules`, `dist`, `__pycache__`, `.env*`. Without it, if a
   developer ever runs `npm install`/creates a venv on the host before
   building the image, the Dockerfile's `COPY . .` step will copy the
   host's (possibly Windows-native) `node_modules`/`__pycache__` into the
   build context and can silently overwrite the container's own
   correctly-built dependencies.

9. **Any script that writes a file path derived from `__file__` must
   account for running inside a bind-mounted container**, where only one
   subdirectory of the repo (e.g. `backend/`) is mounted at `/app` — there
   is no sibling repo root inside the container. A script that does
   `Path(__file__).resolve().parent.parent.parent` to reach "the repo root"
   will instead resolve to `/` on the container's filesystem and fail with
   a permission error. Any "write an informational file near the repo
   root" step should either write inside the mounted directory or be
   wrapped so failure is non-fatal (log and continue, don't crash setup).

10. **A backend script that inserts demo entities directly into the
    database (bypassing the API) must also perform any provisioning side
    effects the API route would normally do.** E.g. if `POST /tenants`
    creates an S3 bucket/prefix as a side effect, a `seed_demo_data.py`
    that writes `Tenant` rows straight to the database must also create
    that bucket/prefix itself — otherwise every subsequent feature that
    assumes the bucket exists (like S3 browsing) breaks for seeded tenants
    specifically.

---

## 1. Context and constraints

- **Deployment target**: AWS ECS (Fargate) only. No Lambda, no Step
  Functions, no SageMaker pipelines. No AWS-managed ML services except as
  launch targets from the portal (EMR Studio, SageMaker Studio) —
  provisioned out-of-band, never created by this app.
- **Database**: DynamoDB only. No RDS, no Aurora. (This constraint matters
  if you ever consider adding real MLflow — MLflow's tracking server needs
  a relational backing store, so a self-hosted tracking server conflicts
  with this constraint; AWS's managed SageMaker-hosted MLflow sidesteps it
  but is a separate infra decision, not something to bolt on casually.)
- **Auth**: Azure Entra ID as identity provider, OIDC/OAuth2 PKCE.
  **Tenancy and role are derived entirely from Entra ID group
  membership** — never from DynamoDB or manual assignment. The ID token's
  `groups` claim (Entra group object IDs) is resolved against a
  `GroupMapping` table (`{groupId: {role, tenantId}}`). On every
  authenticated request in prod mode, `get_current_user` re-resolves from
  the JWT and caches the result as `UserProfile` — never trusts a cached
  role alone. If a user belongs to multiple mapped groups, the
  highest-privilege role wins: **PlatformAdmin > MRM > TenantAdmin >
  DataScientist**.
- **Snowflake connectivity**: OAuth only. The backend exchanges the user's
  Entra access token for a Snowflake OAuth token via RFC 8693
  token-exchange, encrypts it with KMS before caching in DynamoDB, and
  passes it (as a short-lived Secrets Manager reference, never plaintext)
  to EMR/SageMaker jobs so they query Snowflake as the submitting user —
  never a shared service account.
- **Brand**: pull logo/colors from your own design assets — this section
  is intentionally left generic; adapt the brand tokens (primary color,
  background scale, text scale) to your organization's palette instead of
  copying Truist's.
- **Frontend**: React 18 + TypeScript + Vite + Tailwind CSS. All Tailwind
  classes present as literal strings in source (no dynamic class
  construction — breaks JIT detection).
- **Backend**: Python 3.12 + FastAPI, async throughout, Pydantic v2.
- **No placeholders anywhere.** Every endpoint, every DynamoDB operation,
  every React component fully implemented — no "# TODO" or stub functions.
- **Local development**: the entire stack runs via a single
  `docker compose up` with **zero real AWS credentials, zero real Entra ID
  tenant, zero real EMR/SageMaker/Snowflake connections required.**
  LocalStack emulates DynamoDB/S3/STS/KMS/Secrets Manager; EMR/SageMaker/
  Snowflake calls are mocked at the service layer (see §4).

---

## 2. Roles and permissions

Four roles, resolved from Entra groups via `GroupMapping` (see §0.2 for the
"sees all tenants" bug to avoid).

**Platform Admin** — onboard/manage tenants (create/suspend/reactivate);
create/manage all users across all tenants; view all jobs/experiments/
models across all tenants; launch EMR/SageMaker Studio for any tenant;
full audit log access; manage Group Mappings.

**Tenant Admin** — manage users within own tenant only; create/view/cancel
jobs within tenant; view experiments/models within tenant; configure
tenant settings (compute quota, allowed frameworks); launch notebooks
scoped to own tenant; audit log scoped to own tenant. (Tenant self-service
endpoints — `GET/PUT /tenants/{id}`, `GET /tenants/{id}/metrics` — must be
reachable by Tenant Admin for their own tenant, not locked to Platform
Admin only, or the Tenant Admin dashboard/settings pages have nothing to
call.)

**Data Scientist** — submit training jobs (EMR Serverless or SageMaker
Training); view/compare experiments; register model versions from
completed runs; view models belonging to own tenant; launch personal
notebook environment. **Only Data Scientist submits jobs** — this is
intentional, not an oversight; Platform Admin and Tenant Admin can view
everything but don't submit.

**MRM (Model Risk Management)** — read-only across **all** tenants'
models/experiments; download model cards/audit reports; submit governance
review decisions (approve/reject); cannot submit jobs or modify any
resource.

---

## 3. Data model (DynamoDB)

Single-table design, PK/SK pattern, two GSIs (GSI1/GSI2) covering every
access pattern below via an overloaded key scheme
(`GSI1PK`/`GSI1SK`/`GSI2PK`/`GSI2SK`).

- **Tenant**: tenantId (PK), name, status (active/suspended), createdAt,
  createdBy, emrApplicationId, sagemakerDomainId, s3BucketName,
  computeQuotaVcpuHours, allowedFrameworks[]. GSI: by status.
- **GroupMapping**: groupId (Entra group OID, PK), role, tenantId
  (nullable — null for platform-wide roles), description, createdAt,
  createdBy. GSI: by tenantId, by role. Source of truth for tenancy/role.
- **UserProfile**: userId (Entra OID, PK), email, name, tenantId, role
  (resolved from GroupMapping), status, createdAt, lastLoginAt,
  lastResolvedGroupId. GSI: by tenantId, by email.
- **TrainingJob**: jobId, tenantId, userId, name, status
  (queued/running/succeeded/failed/cancelled), framework,
  entryPointScript, s3InputPath, s3OutputPath, computeType
  (emr_serverless/sagemaker), emrJobRunId/sagemakerTrainingJobName,
  hyperparameters, timestamps, instanceType/instanceCount/volumeSizeGb,
  snowflakeDatabase/Schema/Warehouse/Table/Sql (optional — data source),
  driverMemory/executorMemory/maxExecutors (optional, EMR-only resource
  tuning), snowflakeSecretArn. GSI: by tenantId+status, by userId.
- **Experiment**: experimentId, tenantId, name, description, createdBy,
  createdAt, tags. GSI: by tenantId.
- **ExperimentRun**: runId, experimentId, tenantId, jobId (link back to
  the TrainingJob that produced it — see §0.5), status, startTime,
  endTime, params, metrics, tags, artifactUri. GSI: by experimentId, by
  tenantId (also index by runId alone within a tenant, so a run can be
  looked up by ID without knowing its experimentId — needed by the model
  card endpoint, which only stores `runId` on `ModelVersion`).
- **ModelVersion**: modelId, tenantId, name, version (int), stage
  (None/Staging/Production/Archived), runId, framework, artifactUri,
  description, inputSchema, outputSchema, hasExplainer, driftBaselineUri,
  registeredAt/By, promotedAt/By. GSI: by tenantId+stage, by name+version.
  Promoting to Production must require an approved GovernanceReview for
  that model (enforce server-side, return 400 otherwise — don't just rely
  on UI to prevent it).
- **GovernanceReview**: reviewId, modelId, tenantId, modelName,
  modelVersion, reviewedBy, decision (approved/rejected/pending),
  comments, conditions, createdAt, reviewedAt, expiresAt. GSI: by modelId,
  by tenantId.
- **AuditEvent**: eventId, tenantId, userId, action, resourceType,
  resourceId, timestamp, ipAddress, userAgent, details. GSI: by
  tenantId+timestamp, by userId+timestamp. Written from every mutating
  route.
- **NotebookSession**: sessionId, userId, tenantId, sessionType
  (emr_studio/sagemaker_studio), presignedUrl, urlExpiresAt, createdAt,
  status. GSI: by userId.
- **SnowflakeTokenCache**: userId (PK), snowflakeToken (KMS-encrypted),
  expiresAt, issuedAt, tenantId, snowflakeUsername. DynamoDB TTL on
  `expiresAt` for auto-expiry. Plaintext token never logged.

---

## 4. Backend (FastAPI)

### Project structure

```
backend/
├── app/
│   ├── main.py                      # mounts every router, CORS, request logging
│   ├── config.py                    # pydantic-settings; ALL env vars incl. EMR_STUDIO_ID
│   ├── dependencies.py              # get_current_user, require_role, get_db
│   ├── auth/{oidc.py,models.py}
│   ├── db/
│   │   ├── client.py                # boto3 resource/client factory, LocalStack-aware
│   │   ├── models.py                # Pydantic domain models + single-table Keys builder
│   │   └── repositories/            # one per entity, listed in §3
│   ├── routers/                     # one per resource — see endpoint list below
│   │   └── s3.py                    # NEW vs. a naive first pass — see §0.4
│   ├── services/
│   │   ├── job_service.py           # EMR/SageMaker dispatch + mock modes + status polling
│   │   ├── notebook_service.py      # presigned Studio URLs + mock modes
│   │   ├── audit_service.py
│   │   ├── model_card_service.py
│   │   ├── snowflake_service.py     # OAuth exchange, KMS cipher, SELECT-only SQL guard, mocks
│   │   └── group_resolver_service.py
│   └── middleware/{tenant_scope.py,request_logging.py}
├── requirements.txt
└── scripts/
    ├── create_tables.py             # idempotent, works vs LocalStack or real AWS
    ├── seed_demo_data.py            # idempotent; also seeds a few demo S3 objects (§0.10)
    ├── reset_local_db.py
    ├── setup_local_kms.py           # see §0.9 for the path bug to avoid
    └── setup_snowflake_integration.sql
```

### Router endpoints (implement every one, fully)

Every `GET` list endpoint returns `{items, total, page, pageSize}` — see
§0.1. Every mutating endpoint writes an `AuditEvent`.

**`/auth`**: `GET /auth/me` (resolve + return CurrentUser; 403 with a clear
message if no GroupMapping matches); `GET /auth/token-info` (dev-mode-only
JWT debug view, 403 in prod); `GET /auth/snowflake-token` (token exchange,
returns only `{snowflakeUsername, expiresAt}`, never the raw token).

**`/tenants`**: `POST` (Platform Admin only — creates tenant + S3
bucket/prefix); `GET` list (Platform Admin only); `GET/PUT /{id}` and
`GET /{id}/metrics` (**Tenant Admin for own tenant, or Platform Admin for
any** — see §2 note); `POST /{id}/suspend`, `POST /{id}/reactivate`
(Platform Admin only).

**`/users`**: `POST` (Tenant Admin scoped to own tenant, or Platform
Admin any); `GET` list (Platform Admin sees all, Tenant Admin own tenant);
`GET/PUT .../role`, `PUT .../status`.

**`/jobs`**: `POST` — accepts computeType, framework, entryPointScript,
s3InputPath, hyperparameters, instanceType/Count, volumeSizeGb, optional
snowflakeDatabase/Schema/Warehouse/Table/Sql, optional EMR
driverMemory/executorMemory/maxExecutors. When Snowflake fields present:
fetch the user's cached token, decrypt, re-encrypt into a short-lived
Secrets Manager entry, pass only the ARN to the job (never plaintext
anywhere). Per §0.5, also create the linked ExperimentRun here. `GET` list
(scoped by role), `GET /{id}` (live-status recomputed via job_service —
see mock behavior below), `POST /{id}/cancel`, `GET /{id}/logs`.

**`/experiments`**: full CRUD on experiments and runs, incl.
`PUT .../runs/{id}/metrics|params|tags` (meant to be called by the
training script itself while executing inside the job).

**`/models`**: register/list/get/archive; `PUT .../stage` enforces
approved-governance-review-required-for-Production (§3); `GET .../card`
returns a generated model card (model + linked run's params/metrics +
governance history).

**`/governance`** (MRM + Platform Admin): list/create/get reviews,
`PUT /{id}` submits decision, `GET /export/{modelId}/{ver}` bundles model
card + audit trail.

**`/notebooks`**: `POST /launch` (body: sessionType, tenantId — enforce
tenant access), `GET /sessions` (**paginated envelope**, §0.1).

**`/snowflake`**: `GET /status`, `POST /connect`, `POST /disconnect`,
`POST /query` (SELECT-only, enforced server-side via `sqlparse` — reject
DDL/DML keywords even nested, wrap in `SELECT * FROM (...) LIMIT n`),
`GET /databases`, `.../schemas`, `.../tables`, `.../preview`.

**`/s3`** (§0.4 — new): `GET /browse?prefix=` against the shared
artifacts bucket. Non-admins auto-scoped to `{tenantId}/`; any attempt to
pass a prefix outside that is a 403, enforced server-side not just hidden
in the UI. Returns `{bucket, prefix, folders[], files: [{key, size,
lastModified}]}`.

**`/group-mappings`** (Platform Admin only): full CRUD.

**`/audit`**: `GET /events`, filterable, Platform Admin sees all / Tenant
Admin own tenant.

**`/health`**: `{"status": "ok"}`, used by the Docker healthcheck.

### Security requirements

- Prod mode: validate every JWT against Entra ID JWKS (cached, refreshed
  every 15 min). Dev mode (`AUTH_MODE=dev`): skip JWT validation entirely,
  inject a synthetic `CurrentUser` from `DEV_USER_*` env vars — gated
  strictly by `AUTH_MODE == "dev"`, must never activate in prod. In dev
  mode, null `tenantId` for **every** platform-wide role (Platform Admin
  **and MRM** — §0.2), not just Platform Admin.
- Group resolution re-runs from the JWT on every prod-mode request, never
  trusts a cached role. Highest-privilege-wins on multiple group matches.
- Tenant isolation enforced at both the middleware/dependency layer
  (non-Platform-Admin auto-scoped) **and** the data layer (DynamoDB
  condition expressions checking tenantId matches on writes).
- Snowflake tokens: KMS-encrypted before DynamoDB storage; passed to
  compute jobs only as a Secrets Manager ARN with matching TTL, deleted
  after job completion/failure; never in env vars, task defs, S3, or logs.
- `/snowflake/query`: SELECT-only via `sqlparse`, reject
  CREATE/DROP/ALTER/INSERT/UPDATE/DELETE/MERGE/TRUNCATE/GRANT/REVOKE/etc.
  even nested inside subqueries.
- `/s3/browse`: tenant-prefix enforcement at the API layer (§0.4).

### Mock service behavior (`EMR_MOCK_MODE`, `SAGEMAKER_MOCK_MODE`,
`SNOWFLAKE_MOCK_MODE`, default `true` for local dev)

- EMR/SageMaker job submission returns fake IDs (`mock-jr-{uuid4}`,
  `mock-smj-{uuid4}`); `GET /jobs/{id}` recomputes a synthetic status
  progression purely from `createdAt` elapsed time (queued <5s → running
  <30s → succeeded ≥30s) for any **non-terminal** job — including old
  seeded jobs, whose elapsed time will already exceed 30s by the time
  anyone queries them, so they'll read as `succeeded` immediately. That's
  correct mock behavior, not a bug — only a freshly-submitted job shows
  the transient queued/running states.
- Notebook launch returns fake presigned URLs
  (`https://mock-emr.local/session/{uuid}`, `https://mock-studio.local/...`).
- Snowflake: fake token exchange, deterministic mock catalog (3 databases,
  4 schemas, 3 tables with realistic column schemas), 10 synthetic rows
  per query/preview shaped to match the detected table's schema when
  possible. **S3 browsing is real even in mock mode** — LocalStack
  actually implements S3, so don't gate it behind a mock flag.
- All mock responses must be structurally identical (same field
  names/types) to real responses.

### `config.py` — env vars (defaults sensible for local dev)

Same variable set as a standard build of this system
(`AUTH_MODE`, `DEV_USER_*`, `ENTRA_*`, AWS/DynamoDB/S3/KMS/Secrets Manager
endpoints, `EMR_SERVERLESS_APPLICATION_ID`, **`EMR_STUDIO_ID`** (§0.3,
separate from the Serverless app id), `EMR_MOCK_MODE`,
`SAGEMAKER_EXECUTION_ROLE_ARN`, `SAGEMAKER_DOMAIN_ID`,
`SAGEMAKER_MOCK_MODE`, `SNOWFLAKE_*`, `SNOWFLAKE_MOCK_MODE`,
`KMS_SNOWFLAKE_KEY_ARN`, `KMS_ENDPOINT_URL`,
`SECRETS_MANAGER_ENDPOINT_URL`, `SECRETS_MANAGER_JOB_TOKEN_PREFIX`,
`CORS_ALLOWED_ORIGINS`). When an endpoint override (LocalStack) is set and
no real AWS credentials are provided, inject dummy `test`/`test`
credentials so boto3 doesn't fail on missing credentials.

---

## 5. Frontend (React + TypeScript)

Same overall structure as a standard build: `auth/` (MSAL + demo-mode
role selector, `AuthContext` treats `GET /auth/me` as the only
authoritative source of role/tenant — decoding the ID token's `groups`
claim client-side is display/debug only), `api/` (one thin module per
resource, **every list call typed as `Paginated<T>` and the backend must
actually return that shape — §0.1**), `components/` (shared UI kit +
`jobs/JobSubmitForm.tsx` + `snowflake/*` + **new `s3/S3Browser.tsx`**),
`pages/` (role-gated routes — Data Scientist only for `/workspace/submit`,
per §2), `hooks/` (`usePolling`, `useTenantContext`, `useSnowflake`),
`types/platform.ts` (mirrors every backend Pydantic model field-for-field,
camelCase).

### Job submission wizard — 7 steps

1. Compute type (EMR Serverless / SageMaker) — visual cards
2. Framework (pytorch/tensorflow/sklearn/xgboost) — visual cards
3. Data source — tabs: **Snowflake** (connect banner → table browser →
   preview → optional custom-SQL override) vs **S3** (real folder browser
   per §0.4, `S3Browser` component: breadcrumb navigation, click a folder
   to descend, click a file to select it as the path, "use this folder"
   shortcut for folder-level inputs — plus a manual text field kept as an
   editable override, same UX pattern as Snowflake's custom-SQL override)
4. Script (entry point S3 path, output S3 path)
5. Resources (instance type/count/volume; EMR also: driver/executor
   memory, max executors — these must actually flow into the job's Spark
   submit parameters and be persisted on the job record, not just
   collected in the UI and discarded)
6. Hyperparameters (dynamic key-value editor)
7. Review and submit — full config summary, warn if the Snowflake token
   will expire before an estimated completion time

### Other UX requirements

Snowflake connection banner: three states (connected/not-connected/
expired) polled every 60s via `GET /snowflake/status`. Group Mappings page
(Platform Admin only): CRUD table + helper text on finding an Entra group
Object ID. Experiment comparison: side-by-side runs table, highlight best
value per metric column (lower-is-better heuristic for names containing
"loss"/"psi"/"error", higher-is-better otherwise). Notebook launcher: two
visual cards, launch opens the presigned URL in a new tab, active-sessions
list below. Governance review: rendered model card (not raw JSON dump),
approve/reject with required comment, read-only for non-MRM. All pages:
loading/empty/error/pagination states via shared components.

---

## 6. Infrastructure (Docker + ECS)

Three-stage Dockerfiles (`base → dev → prod` for backend;
`base → dev → build → prod` for frontend, prod = nginx serving the built
SPA with SPA-fallback routing + gzip + asset caching), non-root user,
healthchecks. **Both `backend/.dockerignore` and `frontend/.dockerignore`
required (§0.8).** `docker-compose.yml`: LocalStack
(dynamodb,s3,sts,kms,secretsmanager) → one-shot `dynamo-init` (KMS setup →
create tables → seed demo data, reusing the backend `dev` image since
these are Python scripts, not raw AWS CLI) → `backend` (bind-mounted,
`uvicorn --reload`) → `frontend` (bind-mounted, Vite HMR, anonymous volume
over `node_modules`). `scripts/dev.sh`: prereq checks, `.env` bootstrap
from `.env.example`, `docker compose up --build -d`, poll LocalStack then
backend health, print a summary including **the correct role-switch
instructions using `docker compose up -d backend`, not `restart`**
(§0.6). `infrastructure/ecs/*.json` (task defs + service defs, SSM
Parameter Store references for secrets incl. `EMR_STUDIO_ID`),
`infrastructure/dynamodb/tables.json` (CloudFormation, PAY_PER_REQUEST,
both GSIs, TTL on `expiresAt`).

---

## 7. Scripts

`create_tables.py`: idempotent (describe_table first), works against
LocalStack or real AWS depending on whether `DYNAMODB_ENDPOINT_URL` is
set. `seed_demo_data.py`: idempotent per-item (catch
`ConditionalCheckFailedException` and skip rather than duplicate); 3
tenants, 6 group mappings (well-known fake group OIDs), 8 users, 10 jobs
across all statuses, 3 experiments × 8 runs with realistic metrics, 6
model versions across all stages, 2 governance reviews, 15 audit events —
**and also seed a handful of demo files into the S3 bucket under each
tenant's prefix (§0.10), including creating the bucket itself since this
script bypasses the API route that would normally provision it.**
`reset_local_db.py`: confirm prompt, delete + recreate + reseed.
`setup_local_kms.py`: LocalStack KMS key + alias, Secrets Manager
reachability check — **write any informational output file inside the
mounted directory, not three levels up (§0.9), and don't let that write
be fatal if it fails.** `setup_snowflake_integration.sql`: full
ACCOUNTADMIN script for the OAuth security integration.

---

## 8. README

Quick start at the top (`./scripts/dev.sh`, then open localhost:3000
already logged in via `AUTH_MODE=dev`). Explain `AUTH_MODE=dev` and
`VITE_DEMO_MODE=true`. **Role-switching table with the correct
instructions**: edit `DEV_USER_ROLE` in `.env`, then
`docker compose up -d backend` (§0.6) — not `restart`. Entra ID App
Registration steps for prod (groups claim, 200-group token limit +
overage handling). Snowflake OAuth integration setup. Production
migration checklist (disable all mock modes, real Entra/Snowflake/KMS
config, **provision EMR Studio separately and set `EMR_STUDIO_ID`**,
§0.3). Full env var reference table. curl usage examples.

---

## 9. Output format

Produce every file listed across §4–§7, in dependency order (config →
db models/client → repositories → services → middleware → dependencies →
routers → main.py; then frontend types → api → hooks → components →
pages → App.tsx → main.tsx; then Dockerfiles/compose/scripts/infra/
README). No placeholders, no omitted files, no "... rest unchanged."

## 10. Verification checklist — do not skip

- [ ] `docker compose up --build -d` — all containers reach healthy
- [ ] `docker compose logs dynamo-init` shows the seed summary with
      expected counts and **no** tracebacks
- [ ] `curl localhost:8000/health` → `{"status":"ok"}`
- [ ] `curl localhost:8000/auth/me` → resolves to the synthetic dev user
- [ ] Smoke test script passes fully — if it submits a job with Snowflake
      fields, make sure it calls `/snowflake/connect` first (the backend
      correctly rejects a Snowflake-sourced job submission with no active
      connection — that's a test-script bug, not a backend bug, if you hit it)
- [ ] Switch `DEV_USER_ROLE` through all four roles (using
      `docker compose up -d backend` each time, §0.6) and confirm: MRM's
      `/auth/me` shows `tenantId: null` and Models/Experiments/Governance
      return items spanning multiple tenants, not just one (§0.2)
- [ ] `GET /s3/browse` works with no prefix, scoped correctly per role,
      and returns a 403 when a non-admin tries to pass another tenant's
      prefix
- [ ] Frontend: `tsc --noEmit` clean, `npm run build` succeeds
- [ ] `http://localhost:8000/docs` loads and lists every router
