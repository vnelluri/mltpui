# Architecture

FastAPI backend + React SPA for multi-tenant ML model training with MRM
governance. This document describes how the system fits together end to end
and how it is laid out in production. For local-dev instructions see
`README.md`; for per-module Terraform inputs see the `iac/README.md` files.

---

## 1. Components at a glance

| Component | Technology | Where it runs (prod) | Purpose |
|---|---|---|---|
| Frontend | React 18 + Vite + Tailwind, served by nginx | ECS Fargate (control plane) | Role-gated SPA; pure static serving, empty task role |
| Backend | FastAPI, Pydantic v2, boto3 | ECS Fargate (control plane) | All business logic, tenancy enforcement, job dispatch |
| Data store | DynamoDB single table + GSIs + TTL | Control-plane account | Tenants, jobs, experiments, models, reviews, feature store, audit, run tokens |
| Artifacts | S3 (`ml-platform-artifacts-*`) | Control-plane account | Model binaries, uploads, EMR Studio workspaces |
| Training compute | EMR Serverless / SageMaker Training | Dataplane account (per tenant) | Launch targets for training jobs |
| Notebooks | EMR Studio (SSO), SageMaker Studio | Dataplane / platform-global | Deep-linked from the UI; backend never calls the Studio API |
| Identity | Azure Entra ID (OIDC) | External | Authentication + role/tenant derivation from group names |
| Data warehouse | Snowflake (OAuth token exchange) | External | Per-user data access from the UI and from training jobs |
| Secrets/config | SSM Parameter Store, Secrets Manager, KMS | Both accounts | Config injection, token encryption, per-job credential transit |

Per-tenant compute infrastructure (EMR Serverless applications, execution
roles, tenant KMS keys) is **not** in this repo — it is created by the
companion **`tmt-dataplane`** repository (see §6).

## 2. Repository layout

```
backend/
  app/
    main.py             FastAPI entrypoint: routers, CORS, request logging
    config.py           Settings (env vars; mock-mode flags; endpoints)
    auth/               OIDC validation, TokenPayload / CurrentUser models
    dependencies.py     get_current_user, role guards, tenant scoping
    middleware/          Request logging
    routers/            HTTP layer: auth, tenants, jobs, experiments,
                        feature_store, models, governance, notebooks,
                        s3, snowflake, audit, health
    services/           Business logic: job_service, run_token_service,
                        snowflake_service, dataplane_service,
                        tenant_provisioning_service, model_card_service,
                        notebook_service, feature_store_service,
                        membership_service, audit_service
    db/                 DynamoDB client + repositories (repos own all
                        item shapes; single-table design)
  iac/                  Terraform module: backend ECS service + IAM
frontend/
  src/
    App.tsx             Role-gated routes (react-router v6)
    pages/{admin,tenant,workspace,governance,snowflake,audit,features}/
    api/ auth/ components/ hooks/ lib/ types/
  iac/                  Terraform module: frontend ECS service (nginx)
emr-studio/iac/         Terraform module: platform-global EMR Studio (SSO)
scripts/                dev.sh (compose bring-up), test-api.sh (smoke test)
docker-compose.yml      Full local stack (LocalStack + backend + frontend)
```

## 3. Overall system flow

### 3.1 Request lifecycle

```
Browser (SPA) ──HTTPS──► ALB ──► Frontend (nginx, static)
      │
      └──REST/JSON /api──► ALB ──► Backend (FastAPI :8000)
                                      │ get_current_user (JWT → CurrentUser)
                                      │ role guard + tenant scoping
                                      ▼
                              router → service → repository → DynamoDB
                                      │
                                      ├─► EMR Serverless / SageMaker (job submit)
                                      ├─► S3 (artifacts, presigned uploads)
                                      ├─► KMS + Secrets Manager (tokens)
                                      └─► EventBridge (tenant provisioning)
```

Every request passes through `get_current_user`
(`backend/app/dependencies.py`), which produces a `CurrentUser`
(`backend/app/auth/models.py`). Every downstream query is tenant-scoped
through that object — **never bypass tenant scoping**.

### 3.2 Authentication and authorization

- **Identity**: Azure Entra ID OIDC. The SPA obtains a JWT; the backend
  validates it (issuer, audience, signature) in `app/auth/oidc.py`.
- **Roles from groups**: memberships are derived from group names following
  the convention `myapp-{tenantId}-{role}` (e.g.
  `myapp-team-a-datascientist`) plus platform-level groups
  (`myapp-platform-admin`, `myapp-mrm`). Group overage (>200 groups) is
  resolved via Microsoft Graph.
- **Roles**: `PlatformAdmin`, `TenantAdmin`, `DataScientist`, `MRM`, plus
  the machine-only `JobRun` role (never held by humans; rejected by every
  normal role guard).
- **Active membership**: a user may hold several (role, tenant) memberships.
  The active pair is selected per request via `X-Active-Role` /
  `X-Active-Tenant` headers and is always validated against the derived
  memberships — switching can select among grants, never elevate.
- **Visibility**: `PlatformAdmin` and `MRM` have cross-tenant read
  visibility (`sees_all_tenants`); everyone else is confined to their
  active tenant.
- **Dev mode**: `AUTH_MODE=dev` short-circuits to a synthetic user built
  from `DEV_USER_*` env vars. Never enable outside local dev.

The frontend mirrors these rules with role-gated routes in
`frontend/src/App.tsx` (`/admin/*`, `/tenant/*`, `/workspace/*`,
`/governance/*`, `/feature-store`, `/snowflake`, `/audit`), but the
frontend gating is UX only — the backend is the enforcement point.

### 3.3 Training job flow (the core path)

1. **Submit** — a DataScientist submits a job from `/workspace/submit`.
   `JobService` (`backend/app/services/job_service.py`) validates that the
   tenant is provisioned (has an EMR Serverless application / execution
   role from the dataplane) and records the job in DynamoDB.
2. **Run token** — `RunTokenService` mints an opaque `mlrt_…` token bound
   to `(tenantId, experimentId, runId)`. Only its SHA-256 hash is stored
   (TTL-expired); the plaintext is returned exactly once.
3. **Snowflake token (optional)** — if the job reads Snowflake, the user's
   per-user OAuth token (see §3.4) is included in the job payload.
4. **Secret transit** — the run token + optional Snowflake token are
   written to a **short-lived Secrets Manager secret**; only the secret ARN
   is passed to the job environment. This is the single transit path for
   job credentials.
5. **Dispatch** — the job is started on EMR Serverless or SageMaker
   Training using the tenant's own execution role
   (`Tenant.executionRoleArn`, passed via `iam:PassRole`). In the account
   split, EMR and secret operations go through `dataplane_client()` (§6).
6. **In-job logging** — the running job reads the secret and calls back to
   the platform API with `Bearer mlrt_…`. The token resolves to a machine
   principal that can only write metrics/params/tags to its own run —
   nothing else. (This is the foundation for a future `tmt-sdk`.)
7. **Completion** — job status is polled/synced; artifacts land in the S3
   artifacts bucket; the trained binary + lineage are attached to a model
   version, which then enters MRM review.

### 3.4 Snowflake per-user OAuth

- The backend exchanges the user's Entra access token for a Snowflake OAuth
  token via **RFC 8693 token exchange** (`snowflake_service.py`), so
  Snowflake sees the actual user identity — no shared service account.
- Tokens are **KMS-encrypted at rest** in DynamoDB. Encryption failures
  fail **closed**: a `KmsEncryptionError` returns 503 rather than ever
  storing or using a plaintext token.
- Tokens reach training jobs only via the per-job Secrets Manager secret
  (§3.3 step 4), never via job arguments or environment values.

### 3.5 Governance (MRM)

Model versions carry model cards (`model_card_service.py`) and go through
review workflows under `/governance` (create review → submit decision).
MRM users have cross-tenant read visibility plus a platform-level `mrm/`
area in the artifacts bucket for upload and browse. All significant actions
are recorded by `audit_service.py` and surfaced at `/audit`.

### 3.6 Notebooks

The backend **deep-links** into notebook environments; it never proxies
them:

- **EMR Studio** — a single platform-global Studio (SSO auth via IAM
  Identity Center federated to Entra). The backend only reads the static
  `EMR_STUDIO_URL` from SSM and redirects the browser.
- **SageMaker Studio** — presigned domain URLs
  (`sagemaker:CreatePresignedDomainUrl`).

**How the Studio connects to a tenant's EMR Serverless application**
(all defined in `emr-studio/iac/main.tf`):

1. **Sign-in** — the browser follows the backend deep link and
   authenticates through IAM Identity Center (Entra federated, groups
   SCIM-synced). The user's group must appear in the module's
   `session_mappings` input, which assigns a session-policy tier; without
   a mapping, no Studio session can start.
2. **Session identity** — every federated session assumes the shared
   **user role**, further restricted by the mapped session policy:
   `basic` can browse EMR Serverless applications and attach a Workspace
   to one; `intermediate` can additionally start/stop applications and
   start/cancel job runs.
3. **Attach** — inside the Studio the user attaches their Workspace to an
   EMR Serverless application as its compute engine. The applications
   offered are the **per-tenant applications created by `tmt-dataplane`**
   (§3.7) — the Studio provisions no compute of its own.
4. **Storage** — Workspace notebook files live at `default_s3_location`,
   a prefix in the control-plane artifacts bucket
   (`s3://ml-platform-artifacts-*/emr-studio-workspaces`).
5. **Network** — AWS's two-security-group model: the Workspace SG may
   reach the Engine SG only on port 18888 (Jupyter Enterprise Gateway);
   the Engine egresses to EMR Serverless / AWS API endpoints (§4.4).

Known limitation: the Studio is platform-global while jobs/data are
per-tenant, so Studio session policies (`basic` / `intermediate` tiers)
cannot scope S3 by tenant prefix — or restrict *which tenant's
application* a user may attach to — the way per-tenant execution roles do
for job submission. Treat notebook attach as platform-wide within a
user's tier. Per-tenant Studios are a later release.

### 3.7 Tenant provisioning

Creating a tenant in the control plane emits an event to **EventBridge**
(`tenant_provisioning_service.py`, `events:PutEvents`). The
`tmt-dataplane` reconcile pipeline consumes it and creates the tenant's
dataplane resources: EMR Serverless application, execution role, and KMS
key (tagged `platform=<name_prefix>` so control-plane IAM conditions cover
them without re-applying Terraform). Until reconciliation completes, job
submission for that tenant fails with `TenantNotProvisionedError`.

### 3.8 Data model

Single DynamoDB table with GSIs and TTL. Repositories under
`backend/app/db/repositories/` own **all** item shapes — routers and
services never construct raw items. TTL is used for run-token expiry and
other short-lived records.

## 4. Production topology

Production runs across **two AWS accounts**:

```
┌─ Control-plane account ─────────────────┐   ┌─ Dataplane account ──────────────┐
│                                         │   │                                  │
│  ALB ─► Frontend (ECS Fargate, nginx)   │   │  Per tenant (from tmt-dataplane):│
│      └► Backend  (ECS Fargate :8000)    │   │   · EMR Serverless application   │
│                                         │   │   · execution role               │
│  DynamoDB (single table)                │   │     (ml-platform-tenant-*-exec)  │
│  S3 artifacts bucket                    │   │   · tenant KMS key               │
│  SSM Parameter Store  (/ml-platform/*)  │   │  Runtime role (ABAC, assumed     │
│  Secrets Manager (OAuth secret,         │   │  with tenantId session tag)      │
│                   per-job secrets)      │   │                                  │
│  EventBridge (provisioning events) ─────┼──►│  reconcile pipeline              │
│  CloudWatch Logs (/ecs/*-backend)       │   │                                  │
└─────────────────────────────────────────┘   └──────────────────────────────────┘
         ▲ OIDC (Entra ID)                         ▲ OAuth token exchange (Snowflake)
```

A **single-account deployment** is also supported: leave
`dataplane_runtime_role_arn` unset and everything runs in one account with
a platform-wide Snowflake KMS key (`KMS_SNOWFLAKE_KEY_ARN` from SSM).

### 4.1 Terraform modules (this repo)

All three are **modules** (no provider/backend blocks); instantiate them
from your per-account pipeline root. Full input documentation lives in each
module's `README.md`.

| Module | Creates |
|---|---|
| `backend/iac` | Backend ECS task definition + service, CloudWatch log group, execution role (image pull / logs / SSM+secret injection), task role (runtime permissions) |
| `frontend/iac` | Frontend ECS task definition + service. Task role intentionally empty — static serving only |
| `emr-studio/iac` | Platform-global EMR Studio (SSO): two security groups, service role, shared user role, `basic`/`intermediate` session policies, session mappings |

Not created here (bring your own from the pipeline root): VPC/subnets, ECS
cluster, ALB + target groups, security groups, DynamoDB table, S3 buckets,
ECR repositories, SSM parameters, the Snowflake OAuth client secret, and
everything in `tmt-dataplane`.

**Why `emr-studio/iac` lives in this repo and not in `tmt-dataplane`:**
in the account split the Studio *deploys* into the dataplane account
(it must sit next to the EMR Serverless applications it attaches to),
which makes `tmt-dataplane` look like the natural home. It stays here
deliberately:

- The module is provider-less and instantiated from a per-account
  pipeline root via a git source, so repo location does not constrain
  which account deploys it.
- Its lifecycle is platform-global, applied-once infrastructure —
  unlike `tmt-dataplane`, whose machinery is a per-tenant EventBridge
  reconcile loop.
- Its contracts point at the control plane: the `url` output lands in
  control-plane SSM (`/ml-platform/emr/studio-url`, read by the
  backend), and Workspace storage is the control-plane artifacts bucket.
- The single-account deployment (§4) has no separate dataplane account
  at all.

Revisit this when per-tenant Studios ship (§3.6 known limitation): at
that point the Studio becomes a per-tenant dataplane resource and
belongs in the `tmt-dataplane` reconcile pipeline.

### 4.2 Backend IAM (task role) — what the app may do

Defined in `backend/iac/main.tf`; the important grants:

- **DynamoDB** — CRUD + Query/Scan on the single table and its indexes.
- **S3** — Get/Put/List on the artifacts bucket.
- **KMS** — Encrypt/Decrypt/GenerateDataKey on any key tagged
  `platform=<name_prefix>` (covers dynamically created per-tenant keys;
  cross-account use additionally requires the key policy grant made by
  `tmt-dataplane`).
- **Secrets Manager** — full lifecycle only under the job-token prefix
  (`SECRETS_MANAGER_JOB_TOKEN_PREFIX`).
- **EMR Serverless** — job-run operations, constrained by the
  `platform=<name_prefix>` resource tag.
- **SageMaker** — Create/Describe/Stop training jobs, presigned domain URLs.
- **iam:PassRole** — only roles matching
  `tenant_execution_role_arn_pattern`, and only to EMR Serverless /
  SageMaker. Without this, real-mode job submission fails.
- **events:PutEvents** — the tenant-provisioning event bus.
- **sts:AssumeRole + TagSession** — the dataplane runtime role (split mode
  only).

### 4.3 Configuration injection

The backend container gets its configuration two ways
(`backend/iac/main.tf` mirrors `backend/app/config.py`):

- **Plain environment** — non-secret settings: `AUTH_MODE=prod`, table and
  bucket names, all `*_MOCK_MODE=false`, Snowflake defaults, the job-token
  secret prefix, the dataplane runtime role ARN.
- **Container secrets** — pulled at task start by the execution role:
  - SSM parameters under `/ml-platform/*`: Entra tenant/client/audience,
    CORS origins, EMR Studio URL, SageMaker domain/training image,
    Snowflake account/token-URL/client-id.
  - Secrets Manager: `SNOWFLAKE_OAUTH_CLIENT_SECRET`.

Frontend configuration (`VITE_*`: API base URL, Entra IDs, demo mode) is
**baked into the bundle at `docker build` time** — pipeline build args, not
runtime configuration. Changing it means rebuilding the image.

### 4.4 Networking

- Both ECS services run in **private subnets** with
  `assign_public_ip = false`, fronted by an ALB (target groups are module
  inputs).
- Backend health check: `GET /health` (both ALB and container-level).
- EMR Studio uses AWS's two-security-group model (Workspace → Engine on
  18888 only); restrict `workspace_egress_cidrs` from its `0.0.0.0/0`
  default to your NAT/VPC-endpoint ranges in production.

### 4.5 Deployment

CI/CD builds and pushes both images to ECR (prod is the default Docker
target: uvicorn for the backend, nginx for the frontend), then applies the
Terraform modules from the per-account pipeline root. Image-only deploys
roll the ECS services to pull the new tag. `desired_count` is
lifecycle-ignored so autoscaling owns it. Step-by-step commands are in
`README.md` → "ECS deployment steps"; the prod cutover checklist is in
"Moving from local dev to production".

## 5. Local dev vs production

Local dev (`./scripts/dev.sh`, `docker-compose.yml`) runs the **same code
paths** with the AWS boundary swapped out:

| Concern | Local dev | Production |
|---|---|---|
| Auth | `AUTH_MODE=dev` synthetic user from `DEV_USER_*` | Entra ID OIDC, groups claim |
| DynamoDB / S3 / STS / KMS / Secrets Manager | LocalStack (`:4566`) | Real AWS |
| EMR / SageMaker / Snowflake | In-process `*_MOCK_MODE=true` | Real services |
| Tenant provisioning | `TENANT_PROVISIONING_MOCK_MODE=true` | EventBridge → `tmt-dataplane` |
| Config | `.env` (from `.env.example`) | SSM + Secrets Manager injection |
| Serving | uvicorn `--reload` / Vite HMR via bind mounts | uvicorn / nginx behind ALB |

Notably, per-job **Secrets Manager transit is real in every mode** —
LocalStack provides it — so dev exercises the same credential path as prod.
A one-shot `dynamo-init` container creates the KMS key, tables, and demo
seed data.

## 6. Control-plane / dataplane account split

The split is optional and activated by setting
`DATAPLANE_RUNTIME_ROLE_ARN` (Terraform: `dataplane_runtime_role_arn`).

- All EMR Serverless calls and per-job secret operations go through
  `dataplane_client(service, tenant_id)`
  (`backend/app/services/dataplane_service.py`): it assumes the dataplane
  runtime role **with a `tenantId` session tag**. The dataplane role's ABAC
  policy scopes tenant-tagged resources to that same tenant — so even a
  tenancy bug in this codebase cannot reach another tenant's tagged
  resources. Credentials and clients are cached per tenant and rotated
  before expiry.
- **KMS and S3 deliberately bypass** the runtime role: their cross-account
  access is granted by resource policies (key policy / bucket policy)
  directly to the backend task role.
- When the ARN is unset, `dataplane_client` returns ordinary shared clients
  — single-account behavior, identical to local dev.

## 7. Security invariants (do not regress)

1. **Tenant scoping is mandatory** — every query flows through
   `CurrentUser`; role/tenant switching validates against derived
   memberships and can never elevate.
2. **Fail closed on encryption** — KMS failure refuses the operation (503);
   a Snowflake token is never stored or used unencrypted.
3. **Run tokens**: plaintext returned exactly once, only the SHA-256 hash
   persisted (with TTL); the machine principal can write only to its own
   run.
4. **Credential transit**: job credentials travel only inside per-job
   Secrets Manager secrets; only the secret ARN reaches the job
   environment.
5. **Least-privilege IAM**: `iam:PassRole` restricted by role-name pattern
   and target service; EMR/KMS access conditioned on the `platform`
   resource tag; job secrets confined to their prefix.
6. **The frontend enforces nothing** — role-gated routes are UX; the
   backend is the sole enforcement point.
