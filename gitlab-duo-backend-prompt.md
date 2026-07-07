# Prompt: ML Training Platform — Backend Project (GitLab Duo edition)

## How to use this document

This is **project 1 of 2** — the backend only. Project 2 is the frontend
(separate prompt file, separate GitLab repo). They integrate over HTTP only
(`VITE_API_BASE_URL` → this backend's `/`) — build and run this project
first, since the frontend has nothing to talk to otherwise.

This spec reflects a working build that was actually run and exercised —
see **§0 Corrections** for real bugs to avoid repeating, most importantly
the authorization one (§0.1) which is easy to get wrong silently.

**GitLab Duo Chat** (conversational, no autonomous multi-file repo
execution): work through this section by section — config/db layer first,
then repositories, then services, then routers one at a time, then
`main.py`, then scripts. **GitLab Duo Workflow / agentic mode**: paste the
whole document as one task, and explicitly ask it to verify itself per
§10 before calling it done.

**No Docker on this machine.** Local dev uses a plain Python virtualenv and
`moto`'s standalone server (`moto_server`) instead of LocalStack — see §5.
Docker is still used, but only inside GitLab CI, to build the deployable
image for ECS (§6) — that runs on GitLab's runners, not your laptop.

---

## 0. Corrections vs. a naive first pass

Real issues hit while building and reviewing this exact system:

1. **Every mutating endpoint MUST have an explicit `require_role(...)`
   dependency — never just `get_current_user`.** This is the single most
   important rule in this spec. It is easy to build every endpoint with
   plain `get_current_user` (any authenticated role) and rely on the
   frontend to hide buttons for roles that shouldn't act — but that is
   not enforcement, it's decoration. A previous pass of this exact system
   shipped with **zero** server-side role checks on job submission,
   experiment/run writes, model registration, and notebook launch — MRM
   (a read-only role by design) could call every one of them directly via
   `/docs`. Fix pattern: read-only `GET` endpoints stay on plain
   `get_current_user` (tenant-scoped); every `POST`/`PUT`/`DELETE` gets a
   `require_role(...)` matching exactly what the UI assumes, e.g.:
   - Submit/cancel a job, register a model: **DataScientist** only (this
     platform's Tenant Admins can view and manage tenant settings, but do
     not submit jobs or register models — that's an intentional,
     stated design choice, not an oversight).
   - Create an experiment/run, log metrics, launch a notebook: **TenantAdmin
     or DataScientist**.
   - Governance decisions: **MRM** only.
   - Tenant/group-mapping CRUD: **PlatformAdmin** only (tenant get/update/
     metrics also reachable by TenantAdmin for their own tenant).
   After writing the restrictions, **actually test cross-role**: switch the
   dev synthetic user to the most-restricted role and confirm a 403, not
   just that the permissive role gets a 200.

2. **"Sees all tenants" must not also require `tenantId is None`.** A
   role that's supposed to see across every tenant (Platform Admin, MRM)
   needs a `sees_all_tenants` check that stands alone. Writing
   `if user.sees_all_tenants and user.tenantId is None:` is a trap — if
   the dev-mode synthetic user's tenant env var happens to be set, MRM
   silently gets scoped to one tenant instead of all of them. Fix at the
   root: the dev-mode synthetic user constructor must null `tenantId` for
   **every** platform-wide role (Platform Admin **and** MRM), and list
   endpoints should check `sees_all_tenants` alone, never combined with a
   tenantId check.

3. **There is no local user directory. Don't build one.** Identity, role,
   and tenant are derived **entirely** from Entra ID group membership,
   resolved fresh against `GroupMapping` on every request — never
   persisted, never cached, never re-read for authorization. Do not
   create a `UserProfile`/`Users` table or a `/users` CRUD API "to have a
   user list somewhere" — it adds a maintenance burden, invites someone to
   wire authorization off the cached copy instead of the live JWT (a real
   security regression), and a "Deactivate user" button backed by such a
   table does nothing to actually revoke access (only removing someone
   from an Entra group does). If you need a login-activity view, treat it
   as a derived audit-log query, not a first-class entity.

4. **EMR Serverless Application ID and EMR Studio ID are different AWS
   resources.** `EMR_SERVERLESS_APPLICATION_ID` is for job submission.
   EMR Studio (the notebook workspace) needs its own `EMR_STUDIO_ID` — a
   separate config variable. This app never creates a Studio; it only
   requests a presigned login URL into one that's provisioned out-of-band.
   Don't reuse one ID for both.

5. **`job_service.live_status()` (or whatever recomputes a job's status
   from elapsed time) must not mutate its argument in place and then get
   compared against itself.** A pattern like:
   ```python
   recomputed = job_service.live_status(job)
   if recomputed.status != job.status:   # BUG if live_status mutates `job` in place
   ```
   silently never persists a status change, because by the time the
   comparison runs, both names point at the same mutated object. Capture
   the previous status in a separate variable **before** calling the
   recompute function. This bug means "submit a job" would look correct
   in the API response (computed live) but the database status would
   never actually update — a real, hard-to-notice bug found by exercising
   the system end-to-end, not by reading the code.

6. **S3 browsing is a first-class feature, not a raw text field.** Build a
   real `GET /s3/browse?prefix=` endpoint against the shared artifacts
   bucket, scoped so non-admins can't browse outside `{tenantId}/`
   (enforced server-side, not just hidden in a UI). This needs no mock
   mode — moto's S3 (§5) genuinely emulates S3, so it's real traffic even
   in local dev.

7. **Jobs and Experiments are related but must not be silently
   disconnected.** A `TrainingJob` (compute execution: status, EMR/
   SageMaker IDs, resource sizing) and an `ExperimentRun` (ML bookkeeping:
   params/metrics/artifactUri) are different concerns — but if
   `POST /jobs` never creates a linked run, submitted jobs never show up
   for comparison unless something else calls back into the Experiments
   API. Recommended: `POST /jobs` auto-creates (or reuses a stable
   per-tenant default) `Experiment` + linked `ExperimentRun`, and syncs the
   run's status whenever the job's status changes — in **every** endpoint
   that recomputes job status, not just the single-job detail endpoint,
   since a list-polling endpoint is often the only one the frontend
   actually calls.

8. **A script that writes demo/seed entities directly to the database,
   bypassing the normal API route, must also perform whatever
   provisioning side effect that route would have done.** E.g. if
   `POST /tenants` creates an S3 bucket/prefix as a side effect, a
   `seed_demo_data.py` that writes `Tenant` rows straight to the database
   must create that bucket/prefix itself too.

9. **Feature-store / experiment-tracking integrations (Feast, MLflow) are
   real candidates but are training-script-side concerns, not platform
   orchestration concerns — keep them there.** If you build a preview/demo
   of either (optional, not required for a first release), make it
   obviously a preview: a real, persisted registry entity (e.g. a
   `FeatureView`) is fine, but batch/online preview data should be clearly
   synthetic and labeled as such in the API/docs — don't let a demo
   feature imply a production integration that doesn't exist.

---

## 1. Context and constraints

- **Deployment target**: AWS ECS (Fargate) only, deployed via GitLab CI
  (§6). No Lambda, no Step Functions, no SageMaker pipelines. No
  AWS-managed ML services except as launch targets from the portal (EMR
  Studio, SageMaker Studio) — provisioned out-of-band, never created by
  this app.
- **Database**: DynamoDB only. No RDS, no Aurora.
- **Auth**: Azure Entra ID, OIDC/OAuth2 PKCE. Tenancy and role derived
  **entirely** from Entra group membership (`GroupMapping` table maps
  group OID → `{role, tenantId}`), re-resolved on every request in prod
  mode — see §0.1–§0.3.
- **Snowflake connectivity**: OAuth only. Backend exchanges the user's
  Entra access token for a Snowflake token (RFC 8693 token-exchange),
  encrypts it with KMS before caching, passes it to EMR/SageMaker jobs as
  a short-lived Secrets Manager reference — never plaintext anywhere.
- **Local development has no Docker available.** Python virtualenv +
  `uvicorn`, with `moto`'s standalone server providing DynamoDB/S3/KMS/
  Secrets Manager emulation. Full details in §5. Zero real AWS
  credentials, zero real Entra tenant, zero real Snowflake/EMR/SageMaker
  connections required to run and test the whole backend locally.
- **Backend**: Python 3.12 + FastAPI, async throughout, Pydantic v2.
- **No placeholders.** Every endpoint, every DynamoDB operation fully
  implemented — no "# TODO" or stub functions.

---

## 2. Roles and permissions

Four roles, resolved from Entra groups via `GroupMapping`.

- **Platform Admin** — onboard/manage tenants; create/manage Group
  Mappings; view everything across all tenants; launch notebooks for any
  tenant; full audit log.
- **Tenant Admin** — manage own tenant's settings; create/view/cancel jobs
  and experiments within tenant; view models; launch notebooks scoped to
  own tenant; audit log scoped to own tenant. Does **not** submit jobs or
  register models (§0.1).
- **Data Scientist** — submit training jobs; create/compare experiments;
  register model versions; launch personal notebook. The only role that
  submits jobs or registers models.
- **MRM (Model Risk Management)** — read-only across **all** tenants'
  models/experiments; the only role that submits governance decisions
  (approve/reject); cannot submit jobs or modify any other resource
  (§0.1 — must be enforced server-side).

Highest-privilege-wins on multiple Entra group matches: **PlatformAdmin >
MRM > TenantAdmin > DataScientist**.

---

## 3. Data model (DynamoDB)

Single-table design, PK/SK, two GSIs (GSI1/GSI2) via an overloaded key
scheme.

- **Tenant**: tenantId (PK), name, status (active/suspended), createdAt,
  createdBy, emrApplicationId, sagemakerDomainId, s3BucketName,
  computeQuotaVcpuHours, allowedFrameworks[]. GSI: by status.
- **GroupMapping**: groupId (Entra group OID, PK), role, tenantId
  (nullable), description, createdAt, createdBy. GSI: by tenantId, by
  role. **Sole source of truth for tenancy/role** (§0.3 — there is no
  UserProfile table alongside this).
- **TrainingJob**: jobId, tenantId, userId, name, status
  (queued/running/succeeded/failed/cancelled), framework,
  entryPointScript, s3InputPath, s3OutputPath, computeType
  (emr_serverless/sagemaker), emrJobRunId/sagemakerTrainingJobName,
  hyperparameters, timestamps, instanceType/instanceCount/volumeSizeGb,
  snowflakeDatabase/Schema/Warehouse/Table/Sql (optional data source),
  driverMemory/executorMemory/maxExecutors (optional EMR tuning),
  snowflakeSecretArn, **experimentId, experimentRunId** (link to the
  auto-created run, §0.7). GSI: by tenantId+status, by userId.
- **Experiment**: experimentId, tenantId, name, description, createdBy,
  createdAt, tags. GSI: by tenantId.
- **ExperimentRun**: runId, experimentId, tenantId, jobId, status
  (mirrors JobStatus values, kept in sync — §0.7), startTime, endTime,
  params, metrics, tags, artifactUri. GSI: by experimentId, by tenantId
  **and** a lookup by tenantId+runId alone (needed to find a run without
  knowing its experimentId — e.g. from a job's `experimentRunId`, or from
  a `ModelVersion.runId`).
- **ModelVersion**: modelId, tenantId, name, version (int), stage
  (None/Staging/Production/Archived), runId, framework, artifactUri,
  description, inputSchema, outputSchema, hasExplainer, driftBaselineUri,
  registeredAt/By, promotedAt/By. GSI: by tenantId+stage, by name+version.
  Promoting to Production requires an approved `GovernanceReview` for that
  model — enforce server-side (400 otherwise).
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
  `expiresAt` (note: moto's TTL sweep in local dev may not actively
  auto-delete — harmless for local testing, don't rely on it as a
  correctness mechanism there).
- **FeatureView** (optional, preview-only — §0.9): featureViewId,
  tenantId, name, description, entityColumn, features
  (`[{name, dtype}]`), sourceTable, experimentId (optional link back to
  the experiment it was derived from), createdBy, createdAt,
  lastMaterializedAt. GSI: by tenantId.

---

## 4. Backend structure

```
backend/
├── app/
│   ├── main.py                      # mounts every router, CORS, request logging
│   ├── config.py                    # pydantic-settings; ALL env vars
│   ├── dependencies.py              # get_current_user, require_role
│   ├── auth/{oidc.py,models.py}
│   ├── db/
│   │   ├── client.py                # boto3 resource/client factory — endpoint-url aware (§5)
│   │   ├── models.py                # Pydantic domain models + single-table Keys builder
│   │   └── repositories/            # one per entity in §3 — NO user_repo.py (§0.3)
│   ├── routers/                     # one per resource — see endpoint list below. NO users.py.
│   ├── services/
│   │   ├── job_service.py           # EMR/SageMaker dispatch + mock modes + status polling (§0.5)
│   │   ├── notebook_service.py
│   │   ├── audit_service.py
│   │   ├── model_card_service.py
│   │   ├── snowflake_service.py     # OAuth exchange, KMS cipher, SELECT-only SQL guard, mocks
│   │   ├── group_resolver_service.py
│   │   └── feature_store_service.py # optional, preview-only (§0.9)
│   └── middleware/{tenant_scope.py,request_logging.py}
├── requirements.txt                 # prod deps only
├── requirements-dev.txt             # + moto[server], for local dev (§5) — never in the prod image
└── scripts/
    ├── create_tables.py             # idempotent, works vs moto or real AWS
    ├── seed_demo_data.py            # idempotent; also provisions the bucket + demo S3 objects (§0.8)
    ├── reset_local_db.py
    ├── setup_local_kms.py           # creates a KMS key alias against moto (or real AWS)
    └── setup_snowflake_integration.sql
```

### Router endpoints — implement every one, fully

Every list `GET` returns `{items, total, page, pageSize}` — no exceptions
(a bare array vs. that envelope is the single most common integration bug
between this backend and the frontend project). Every mutating endpoint
writes an `AuditEvent` **and** has an explicit `require_role(...)` per §0.1.

- **`/auth`**: `GET /auth/me` (resolve + return CurrentUser; 403 with a
  clear message if no GroupMapping matches); `GET /auth/token-info`
  (dev-mode-only JWT debug, 403 in prod); `GET /auth/snowflake-token`
  (token exchange, returns only `{snowflakeUsername, expiresAt}`).
- **`/tenants`**: `POST`/list (PlatformAdmin only — create also
  provisions an S3 bucket/prefix); `GET/PUT /{id}` + `GET /{id}/metrics`
  (TenantAdmin for own tenant, or PlatformAdmin for any); `suspend`/
  `reactivate` (PlatformAdmin only).
- **`/jobs`**: `POST` (**DataScientist only** — accepts computeType,
  framework, entryPointScript, s3InputPath, hyperparameters,
  instanceType/Count, volumeSizeGb, optional snowflakeDatabase/Schema/
  Warehouse/Table/Sql, optional EMR driverMemory/executorMemory/
  maxExecutors; on Snowflake fields present, fetch+decrypt the user's
  cached token, re-encrypt into a short-lived Secrets Manager entry, pass
  only the ARN to the job; auto-create the linked Experiment+Run per
  §0.7); `GET` list (role-scoped, recomputes + **persists** live status
  and syncs the linked run on every call — §0.5); `GET /{id}`; `POST
  /{id}/cancel` (TenantAdmin or DataScientist); `GET /{id}/logs`.
- **`/experiments`**: `POST` experiment/run, `PUT .../metrics|params|tags`
  (TenantAdmin or DataScientist); `GET` list/detail (any authenticated
  role, tenant-scoped or all-tenant for MRM/PlatformAdmin).
- **`/models`**: `POST` register (**DataScientist only**); `GET` list/
  versions/detail (any role); `PUT .../stage` + `POST .../archive`
  (TenantAdmin); `GET .../card`.
- **`/governance`** (MRM only for writes; MRM+PlatformAdmin for reads):
  list/create/get reviews, `PUT /{id}` decision, `GET /export/...`.
- **`/notebooks`**: `POST /launch` (TenantAdmin or DataScientist,
  tenant-enforced); `GET /sessions`.
- **`/snowflake`**: `GET /status`, `POST /connect`, `POST /disconnect`,
  `POST /query` (SELECT-only via `sqlparse` — reject DDL/DML even
  nested, wrap in `SELECT * FROM (...) LIMIT n`), `GET /databases`,
  `.../schemas`, `.../tables`, `.../preview`. Any authenticated role.
- **`/s3`** (§0.6): `GET /browse?prefix=` — non-admins auto-scoped to
  `{tenantId}/`, 403 on any attempt outside it.
- **`/feature-store`** (optional, §0.9): `POST /views` (DataScientist
  only), `GET /views` + `/{id}` (any role), `GET /{id}/preview` (any
  role), `POST /{id}/materialize` (TenantAdmin or DataScientist).
- **`/group-mappings`** (PlatformAdmin only): full CRUD.
- **`/audit`**: `GET /events` (PlatformAdmin sees all, TenantAdmin own
  tenant).
- **`/health`**: `{"status": "ok"}`.

### Security requirements

- Prod mode: validate every JWT against Entra JWKS (cached, 15-min
  refresh). Dev mode (`AUTH_MODE=dev`): skip validation, inject a
  synthetic `CurrentUser` from `DEV_USER_*` env vars — gated strictly by
  `AUTH_MODE == "dev"`. Null `tenantId` for **every** platform-wide role
  (Platform Admin **and** MRM — §0.2).
- Tenant isolation at both the dependency layer (non-Platform-Admin
  auto-scoped) and the data layer (condition expressions on writes).
- Snowflake tokens: KMS-encrypted at rest; passed to compute jobs only as
  a Secrets Manager ARN with matching TTL, deleted after job completion/
  failure; never plaintext in env vars, task defs, S3, or logs.
- `/snowflake/query`: SELECT-only via `sqlparse`.
- `/s3/browse`: tenant-prefix enforcement at the API layer.

### Mock service behavior (`EMR_MOCK_MODE`, `SAGEMAKER_MOCK_MODE`,
`SNOWFLAKE_MOCK_MODE`, default `true` for local dev)

- EMR/SageMaker job submission returns fake IDs; `GET /jobs` (list, not
  just detail — §0.5) recomputes a synthetic status progression purely
  from `createdAt` elapsed time (queued <5s → running <30s → succeeded
  ≥30s) for any non-terminal job, and **persists** the change plus syncs
  the linked run.
- Notebook launch returns fake presigned URLs.
- Snowflake: fake token exchange, deterministic mock catalog (a few
  databases/schemas/tables with realistic column schemas), synthetic rows
  shaped to match the detected table's schema.
- **S3 browsing is real even in mock mode** (moto genuinely emulates S3 —
  no mock flag needed for it).
- All mock responses are structurally identical (same field names/types)
  to real responses.

---

## 5. Local development — no Docker

### The core idea

Replace LocalStack (which needs Docker) with **`moto`'s standalone server
mode** (`pip install moto[server]`, pure Python, no Docker, no JVM). From
the application's point of view this is a near drop-in swap: both LocalStack
and moto expose AWS-compatible HTTP endpoints that boto3 talks to via a
plain `endpoint_url=` override — the app code (`db/client.py`'s boto3
client/resource factory) barely changes, just the URL it points at and
how the emulator process is started.

```
moto_server -p 5000
```

starts one process that emulates DynamoDB, S3, KMS, and Secrets Manager
(everything this app touches) on a single port. Point every
`*_ENDPOINT_URL` setting at `http://localhost:5000`.

### Setup

1. Prerequisite: Python 3.12 (no Docker, no Java, no Node needed for the
   backend project).
2. `python -m venv .venv` then activate it
   (`source .venv/bin/activate` / `.venv\Scripts\activate` on Windows).
3. `pip install -r requirements.txt -r requirements-dev.txt`.
4. Copy `.env.example` to `.env` — defaults already point every
   `*_ENDPOINT_URL` at `http://localhost:5000` and `AUTH_MODE=dev`.
5. Run `scripts/dev.py` (see below) — starts moto_server as a background
   process, waits for it, runs setup_local_kms → create_tables →
   seed_demo_data, then starts `uvicorn app.main:app --reload`.

### `scripts/dev.py` — implement fully (Python, not bash, so it runs
identically on Windows/macOS/Linux with no shell-specific syntax)

- Checks Python version, prints a clear error if `moto[server]` isn't
  importable (tell the user to `pip install -r requirements-dev.txt`).
- Copies `.env.example` to `.env` if `.env` doesn't exist yet.
- Launches `moto_server -p 5000` via `subprocess.Popen`, capturing its
  PID so it can be cleaned up on exit (register an `atexit` handler /
  handle `KeyboardInterrupt` to terminate the child process — don't leave
  an orphaned moto_server running after Ctrl+C).
- Polls `http://localhost:5000/` (or any lightweight endpoint) in a loop
  with a timeout (e.g. 20s) until it responds, printing dots.
- Runs `setup_local_kms.py`, then `create_tables.py`, then
  `seed_demo_data.py` as subprocesses, failing loudly (non-zero exit,
  clear message) if any of them fail — don't silently continue to start
  the API server against a half-initialized backing store.
- Starts `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` as
  the final foreground process (so Ctrl+C in this terminal stops both
  uvicorn and, via the exit handler, moto_server).
- Prints a summary once uvicorn is confirmed listening:
  ```
  ✅ Backend running locally (no Docker)

  API:         http://localhost:8000
  API docs:    http://localhost:8000/docs
  Moto (AWS emulation): http://localhost:5000

  Demo credentials (AUTH_MODE=dev):
    Role:     PlatformAdmin  (change DEV_USER_ROLE in .env)
    Tenants:  Risk Analytics · Fraud Detection · Compliance

  To change your demo role:
    Edit DEV_USER_ROLE in .env, then stop (Ctrl+C) and re-run this script
    — environment variables are read once at process startup, so a plain
    file edit has no effect until the process restarts. (There is no
    Docker-container-recreate step to worry about here — just restart
    the process, which is simpler than the Docker equivalent.)

  To reset demo data:
    python scripts/reset_local_db.py   (moto_server must still be running)

  To stop:
    Ctrl+C in this terminal (stops uvicorn and moto_server together)
  ```

### `requirements-dev.txt`

```
moto[server]
```
(kept separate from `requirements.txt` so the production/CI image never
installs a mock AWS server).

### Adjustments to scripts from a Docker-based build

- `create_tables.py` / `seed_demo_data.py` / `reset_local_db.py`: same
  logic as before, just default `*_ENDPOINT_URL` to
  `http://localhost:5000` instead of a LocalStack hostname, and drop any
  Docker-bind-mount-path assumptions (e.g. a script that computed a
  "repo root" path by walking up from `__file__` assuming a container
  layout — with no container, `__file__`'s real location on disk is just
  the actual repo root's `backend/scripts/`, so path assumptions actually
  get *simpler*, not harder, without Docker).
- `setup_local_kms.py`: creates a KMS key + alias against
  `http://localhost:5000` via boto3 exactly as it would against LocalStack
  or real AWS — moto's KMS supports `create_key`/`create_alias`/
  `describe_key`/`encrypt`/`decrypt`.

### `scripts/test-api.sh` (or `.py`)

Smoke-test script — unchanged in spirit from a Docker-based build: health
check, auth/me, then exercise create/list across tenants (as
PlatformAdmin dev role), jobs (as DataScientist — remember: connect to
Snowflake first before submitting a job with Snowflake fields, or it
correctly 400s), experiments, models, group-mappings, audit. Requires
`curl` + `jq` (or rewrite in Python using `requests` if you'd rather avoid
that dependency on the developer's machine — reasonable either way, note
whichever you pick in the README).

### Troubleshooting

- **"Address already in use" on port 5000 (moto_server) or 8000
  (uvicorn)**: something from a previous run is still alive — find and
  stop it (`lsof -i :5000` / `netstat -ano | findstr :5000` on Windows)
  rather than picking a different port ad hoc, since every `*_ENDPOINT_URL`
  in `.env` is hardcoded to port 5000 by default.
- **`ModuleNotFoundError: moto`**: `requirements-dev.txt` wasn't
  installed — `pip install -r requirements.txt -r requirements-dev.txt`.
- **Edited `DEV_USER_ROLE` in `.env` but the API still resolves the old
  role**: environment variables are read once at process startup (via
  `pydantic-settings`, cached). A plain file edit has no effect until the
  process restarts — stop `scripts/dev.py` (Ctrl+C) and re-run it. There
  is no container-recreate-vs-restart distinction to worry about here
  (that was a Docker-specific gotcha); a plain process restart always
  picks up the new `.env`.
- **`seed_demo_data.py` fails partway through**: it's idempotent per
  item, so just re-run it — already-created entities are skipped, not
  duplicated. If it's failing on the same entity every time, check
  moto_server's own terminal output for the actual AWS-API-shaped error.

---

## 6. Infrastructure & GitLab CI (still uses Docker — in CI only)

Local dev never touches Docker, but ECS Fargate still needs a container
image, and that gets built by **GitLab CI runners**, not the developer's
laptop.

**`Dockerfile`** (used only by CI, never by a developer locally): a
simple two-stage build — `base` installs `requirements.txt` (not
`requirements-dev.txt`), `prod` copies `./app` and runs
`uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2`, non-root
user, `HEALTHCHECK` against `/health`.

**`.gitlab-ci.yml`**:
```yaml
stages: [test, build]

test:
  stage: test
  image: python:3.12-slim
  script:
    - pip install -r requirements.txt -r requirements-dev.txt
    - python -m py_compile $(find app scripts -name "*.py")
    # add: pytest, if a test suite exists

build:
  stage: build
  image: docker:24
  services:
    - docker:24-dind
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - echo "$CI_REGISTRY_PASSWORD" | docker login -u "$CI_REGISTRY_USER" --password-stdin $CI_REGISTRY
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

**`infrastructure/ecs/`**: task definitions (backend, memory 1024/cpu
512), service definitions (desired count 2, health check grace period
60s), SSM Parameter Store references for secrets including `EMR_STUDIO_ID`
(§0.4, separate from `EMR_SERVERLESS_APPLICATION_ID`).

**`infrastructure/dynamodb/tables.json`**: CloudFormation, PAY_PER_REQUEST,
both GSIs, TTL on `expiresAt`.

---

## 7. README

Quick start at the top: clone → venv → `pip install` → `python
scripts/dev.py`. Explain `AUTH_MODE=dev` and the moto-vs-LocalStack
substitution plainly (so a reader who's used the Docker-based version of
this pattern elsewhere isn't confused). Role-switching table with the
**process-restart** instruction (§5), not a container-recreate
instruction. Entra ID App Registration steps for prod (groups claim,
200-group token limit). Snowflake OAuth integration setup. Production
migration checklist (disable all mock modes, real Entra/Snowflake/KMS
config, provision EMR Studio separately and set `EMR_STUDIO_ID`). Full
env var reference table. Note clearly: **this backend project has no
Docker dependency for local development — Docker only appears in GitLab
CI, to build the ECS deployment image.**

---

## 8. Output format

Produce every file in dependency order: config → db models/client →
repositories → services → middleware → dependencies → routers → main.py;
then scripts; then Dockerfile/.gitlab-ci.yml/infra; then README. No
placeholders, no omitted files.

## 9. Verification checklist — do not skip

- [ ] `python scripts/dev.py` — moto_server starts, setup scripts run
      without error, uvicorn comes up
- [ ] `curl localhost:8000/health` → `{"status":"ok"}`
- [ ] `curl localhost:8000/auth/me` → resolves to the synthetic dev user
- [ ] Smoke test script passes fully
- [ ] Switch `DEV_USER_ROLE` through all four roles (restarting the
      process each time, §5) and confirm: MRM gets a 403 on job
      submission, experiment creation, model registration, and notebook
      launch (§0.1) but 200s on every read; MRM's `/auth/me` shows
      `tenantId: null` and cross-tenant reads actually span tenants (§0.2)
- [ ] `GET /s3/browse` works with no prefix, tenant-scoped correctly, 403
      on cross-tenant prefix attempts
- [ ] Submit a job as DataScientist, then poll `GET /jobs` a few times
      over ~35s and confirm the linked `ExperimentRun`'s status actually
      progresses queued → running → succeeded (§0.5 and §0.7 — this is
      the check that catches the mutate-in-place bug if it's present)
- [ ] `http://localhost:8000/docs` loads and lists every router
