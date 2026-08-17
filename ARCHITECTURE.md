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
| Identity | Cognito (Hosted UI) ← SAML ← Azure AD | External | Authentication + role/tenant derivation from group names (`custom:groups`) |
| Data warehouse | Snowflake (External OAuth via Entra) | External | Per-user data access from the UI and from training jobs |
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
    auth/               Cognito ID-token validation, TokenPayload / CurrentUser models
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
                                      └─► KMS / IAM / EMR Serverless (tenant provisioning)
```

Every request passes through `get_current_user`
(`backend/app/dependencies.py`), which produces a `CurrentUser`
(`backend/app/auth/models.py`). Every downstream query is tenant-scoped
through that object — **never bypass tenant scoping**.

### 3.2 Authentication and authorization

- **Identity**: AWS Cognito federated to Azure AD via SAML. The SPA signs
  in through the Cognito Hosted UI (Amplify) and sends the **Cognito ID
  token** as the Bearer credential; the backend validates it (issuer,
  audience, signature, `token_use=id`) in `app/auth/cognito.py`. User info
  (email, given_name) and Azure AD group names (`custom:groups`,
  comma-separated) come from the SAML attribute mapping — no Microsoft
  Graph calls.
- **Roles from groups**: memberships are derived from group names following
  the convention `myapp-{tenantId}-{role}` (e.g.
  `myapp-team-a-datascientist`) plus platform-level groups
  (`myapp-platform-admin`, `myapp-mrm`).
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

- Snowflake tokens are minted at **Entra** via the **authorization-code +
  refresh** flow (`snowflake_service.py`): the user consents once
  ("Connect Snowflake" → Entra → backend callback), the KMS-encrypted
  refresh token lets the backend re-mint without the user present, and
  Snowflake's **External OAuth integration trusting Entra** validates the
  tokens directly — Snowflake sees the actual user identity, no shared
  service account, no Snowflake-side token endpoint.
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

- **EMR Studio** — a single platform-global Studio. In **both** auth modes
  the backend only reads the static `EMR_STUDIO_URL` from SSM and redirects
  the browser; AWS's hosted sign-in flow authenticates the user (IAM /
  IAM-federation for `auth_mode = IAM`, IAM Identity Center for `SSO`). The
  backend never calls the EMR Studio API. See `docs/EMR_STUDIO_IAM_MODE.md`.
- **SageMaker Studio** — presigned domain URLs
  (`sagemaker:CreatePresignedDomainUrl`).

**How the Studio connects to a tenant's EMR Serverless application**
(all defined in `tmt-dataplane/modules/emr-studio/main.tf`):

1. **Sign-in** — the browser follows the backend deep link and AWS's
   hosted flow authenticates the user. **IAM mode (default):** the access
   URL redirects to IAM sign-in — or, with IAM federation to Entra, to a
   SAML sign-in that lands the user in a per-tier role
   (`sts:AssumeRoleWithSAML` via the admin-created SAML provider).
   **SSO mode:** IAM Identity Center (Entra federated, groups SCIM-synced);
   the user's group must appear in the module's `session_mappings` input —
   without a mapping, no Studio session can start.
2. **Session identity** — the tier bounds what the session can do:
   `basic` can browse EMR Serverless applications and attach a Workspace
   to one; `intermediate` can additionally start/stop applications and
   start/cancel job runs. In IAM mode the tier is the per-tier role the
   user federated into (`…-emr-studio-basic` / `-intermediate`); in SSO
   mode it is a session policy narrowing the shared user role.
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

Creating a tenant provisions its dataplane resources **directly via boto3**
(`tenant_provisioning_service.py`), through the dataplane runtime role
assumed with a `tenantId` session tag: the per-tenant KMS key, the
execution role (`ml-platform-tenant-{id}-exec`), the EMR Serverless
application (interactive endpoint enabled — the EMR Studio attach
dependency), and the S3 prefix marker. Everything is tagged `tenantId` +
`platform=ml-platform` so IAM ABAC conditions cover the new resources
immediately. Until provisioning succeeds, job submission for that tenant
fails with `TenantNotProvisionedError`.

### 3.8 Data model

Single DynamoDB table with GSIs and TTL. Repositories under
`backend/app/db/repositories/` own **all** item shapes — routers and
services never construct raw items. TTL is used for run-token expiry and
other short-lived records.

### 3.9 Tenant lifecycle

A tenant is a **control-plane record first, dataplane infrastructure
second**. §3.7 names the resources; this expands the full
create → provision → active → suspend flow.

**Design principle — synchronous, idempotent steps instead of a
pipeline.** Each resource is created only when the tenant record doesn't
already carry its id, and ids are written onto the record as steps
complete. A failure marks the tenant `failed` with the error recorded
(`Tenant.provisioningError`); `POST /tenants/{id}/provision` re-drives
provisioning, resuming from whatever already exists. There is no event
bus and no reconcile pipeline in the tenant path.

```
PlatformAdmin
  POST /tenants  (routers/tenants.py)
    │ validate tenantId slug (≤30 chars); 409 if exists
    ▼
  tenant_provisioning_service.provision()        (synchronous, idempotent)
    ├─ MOCK: fill mock IDs, S3 prefix, provisioningStatus=active
    └─ PROD: via dataplane_client (runtime role + tenantId session tag)
         1. KMS key + alias ml-platform-snowflake-{id}    → kmsKeyArn
         2. exec role ml-platform-tenant-{id}-exec        → executionRoleArn
            (org permissions boundary attached when
             TENANT_ROLE_PERMISSIONS_BOUNDARY_ARN is set)
         3. EMR Serverless app (interactive endpoint on)  → emrApplicationId
         4. S3 prefix marker (backend credentials)        → s3BucketName
         ├─ all steps ok → provisioningStatus=active  (jobs allowed)
         └─ any failure  → provisioningStatus=failed + provisioningError
                           POST /tenants/{id}/provision resumes from
                           the first missing resource
```

**States** (`Tenant.provisioningStatus`, `Tenant.status`):

| Transition | Trigger | Effect |
|---|---|---|
| create → `active` | `POST /tenants` (mock, or prod success) | Resource ids recorded; jobs allowed |
| create → `failed` | a provisioning step failed | Partial ids persisted; **job submission rejected** (`TenantNotProvisionedError`) |
| `failed`/`pending` → `active` | `POST /tenants/{id}/provision` retry | Resumes idempotently — existing resources are skipped |
| any → `active` | `PUT /tenants/{id}/provisioning` manual write-back | Records out-of-band-provisioned resource ids without running the direct path |
| `active` → `suspended` | `POST /tenants/{id}/suspend` | **Dataplane untouched** — jobs blocked at the API layer, resources persist |
| `suspended` → `active` | `POST /tenants/{id}/reactivate` | Unblocks; no re-provisioning needed |
| `suspended` → `deleted` | `DELETE /tenants/{id}` (`?deleteData=true` to also purge S3) | **Hard deletion** — `deprovision()` tears down app/role in reverse order, KMS key scheduled with a 30-day recovery window; record kept as a tombstone (audit/lineage keep resolving); irreversible via API |

Deletion is deliberately two-step (suspend first, no queued/running jobs)
and idempotent like provisioning: teardown clears each resource id off the
record as it completes, a partial failure records `provisioningError`, and
re-running DELETE resumes. S3 artifacts are **kept by default** (MRM
retention) — `?deleteData=true` is the explicit opt-in to purge the
tenant's prefix. A deleted tenant cannot be reactivated or re-provisioned;
create a new tenant instead.

**Why `tenantId` is chosen, never generated** — the same slug appears in
three independent places that must agree: the Entra group names
(`myapp-{tenantId}-{role}`), the S3 prefix, and the dataplane execution
role name (`ml-platform-tenant-{tenantId}-exec`). The ≤30-char cap
(`_TENANT_ID_RE` in `routers/tenants.py`) exists so that role name stays
under IAM's 64-char limit — a longer slug would validate here and then
fail `iam:CreateRole` at provisioning time.

EMR Studio is **platform-global**, not part of this per-tenant path
(§3.6).

## 4. Production topology

Production runs across **two AWS accounts**:

```
┌─ Control-plane account (tmt monorepo) ──┐   ┌─ Dataplane account (tmt-dataplane) ─────┐
│                                         │   │  account-baseline (applied once):       │
│  ALB ─► Frontend (ECS Fargate, nginx)   │   │   · S3 artifacts bucket + CMK           │
│      └► Backend  (ECS Fargate :8000)    │──►│   · dataplane-runtime role (ABAC)       │
│                                         │   │   · per-job token secrets               │
│  DynamoDB (single table)                │   │   · EMR Studio + basic/intermediate     │
│  SSM Parameter Store  (/ml-platform/*)  │   │     tier roles (IAM auth mode)          │
│  Secrets Manager (Snowflake OAuth)      │   │  Per tenant (created by the backend     │
│  CloudWatch Logs (/ecs/*-backend)       │   │  via the runtime role at POST /tenants):│
│                                         │   │   · EMR Serverless application          │
│                                         │   │   · execution role (…-tenant-*-exec)    │
│                                         │   │   · tenant KMS key                      │
└─────────────────────────────────────────┘   └─────────────────────────────────────────┘
    ▲ Cognito (SAML ← Azure AD)         backend → dataplane (cross-account):
                                        AssumeRole the runtime role (+tenantId
                                        tag) for jobs, secrets AND tenant
                                        provisioning; S3/KMS on the artifacts
                                        bucket by resource policy. (The Studio
                                        tier roles are assumed by USERS via
                                        SAML federation, never by the backend.)
                                        The artifacts bucket and per-job secrets
                                        live in the DATAPLANE account; the
                                        backend reaches them cross-account.
```

A **single-account deployment** is also supported: leave
`dataplane_runtime_role_arn` unset and everything runs in one account with
a platform-wide Snowflake KMS key (`KMS_SNOWFLAKE_KEY_ARN` from SSM).

### 4.1 Terraform modules (this repo)

Both are **modules** (no provider/backend blocks); instantiate them from your
per-account pipeline root. Full input documentation lives in each module's
`README.md`.

| Module | Creates |
|---|---|
| `backend/iac` | Backend ECS task definition + service, CloudWatch log group, execution role (image pull / logs / SSM+secret injection), task role (runtime permissions) |
| `frontend/iac` | Frontend ECS task definition + service. Task role intentionally empty — static serving only |

The **EMR Studio** module lives in the companion **`tmt-dataplane`** repo
(`modules/emr-studio`) — see below. Default `auth_mode = "IAM"` (no Identity
Center): the Studio (no `user_role`), two security groups, and a service role.
Users reach it through the Studio **access URL** (`EMR_STUDIO_URL`), where AWS's
hosted flow signs them in via IAM / IAM-federation — the backend does **not**
presign (`CreateStudioPresignedUrl` isn't in the boto3 SDK). `auth_mode = "SSO"`
uses a shared user role + session policies + session mappings (Identity Center).
See the module README and `docs/EMR_STUDIO_IAM_MODE.md`.

Not created here (bring your own from the pipeline root): VPC/subnets, ECS
cluster, ALB + target groups, security groups, DynamoDB table, S3 buckets,
ECR repositories, SSM parameters, the Snowflake OAuth client secret, and
everything in `tmt-dataplane`.

**The EMR Studio module lives in and is applied by `tmt-dataplane`**
(`modules/emr-studio`), from its `account-baseline` global layer — not this
monorepo. It moved there because, with IAM mode the default, that is where it
belongs:

- `tmt-dataplane`'s root applies `account-baseline`, a **global,
  applied-once-per-account** stack (artifacts bucket, the
  `dataplane-runtime` role). The Studio's applied-once-global lifecycle
  fits `account-baseline` exactly. (Per-tenant resources are no longer a
  pipeline concern — the backend creates them directly, §3.7.)
- All its resources are dataplane-account (Studio, tier roles, SGs), next to
  the EMR Serverless apps they attach to, and its inputs are dataplane-side
  values: `saml_provider_arn` (the admin-created SAML provider the tier roles
  trust for `sts:AssumeRoleWithSAML`), `subnet_ids`, `vpc_id`,
  `artifacts_bucket` (→ `default_s3_location`; the artifacts bucket is a
  **dataplane** resource created by `account-baseline`, reached by the backend
  cross-account), and the `…-tenant-*-exec` pattern (→ the intermediate tier's
  `PassRole`).
- Its `emr_studio_url` output wires into the backend (operator-written SSM
  `/ml-platform/emr/studio-url` → `EMR_STUDIO_URL`); `emr_studio_tier_role_arns`
  and `emr_studio_saml_provider_arn` feed the Entra "Role" claim — not the
  backend.

The control-plane backend **consumes** the Studio (deep-links its access URL,
§3.6) but never applies it — in both auth modes AWS's hosted sign-in flow
authenticates the user, and the backend makes no EMR Studio API call and
assumes no Studio role. Costs borne on the
`tmt-dataplane` side: its `account-baseline` CI/CD role gained EMR-Studio +
studio-IAM-role + SG create permissions, and the Studio's roles get KMS use on
the artifacts CMK. Historically the module lived here and the backend pipeline
applied it (its `url` output fed control-plane SSM); IAM mode removed that SSM
tie and `account-baseline` supplies the global layer the old reasoning assumed
absent, so it moved.

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
- **sts:AssumeRole + TagSession** — the dataplane runtime role (split mode
  only). Tenant provisioning AND deprovisioning also go through that role,
  so its policy (owned by `tmt-dataplane`) needs, beyond the job-path ABAC:
  `kms:CreateKey/CreateAlias/DeleteAlias/ScheduleKeyDeletion`,
  `iam:CreateRole/PutRolePolicy/DeleteRolePolicy/DeleteRole`
  (boundary-conditioned — see `TENANT_ROLE_PERMISSIONS_BOUNDARY_ARN`), and
  `emr-serverless:CreateApplication/StopApplication/DeleteApplication`.

### 4.3 Configuration injection

The backend container gets its configuration two ways
(`backend/iac/main.tf` mirrors `backend/app/config.py`):

- **Plain environment** — non-secret settings: `AUTH_MODE=prod`, table and
  bucket names, all `*_MOCK_MODE=false`, Snowflake defaults, the job-token
  secret prefix, the dataplane runtime role ARN.
- **Container secrets** — pulled at task start by the execution role:
  - SSM parameters under `/ml-platform/*`: Cognito user-pool/app-client IDs,
    CORS origins, EMR Studio URL, SageMaker domain/training image,
    Snowflake account/oauth-scope/client-id, Entra tenant id.
  - Secrets Manager: `SNOWFLAKE_OAUTH_CLIENT_SECRET`.

Frontend configuration (`VITE_*`: API base URL, Cognito IDs, demo mode) is
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
| Auth | `AUTH_MODE=dev` synthetic user from `DEV_USER_*` | Cognito ID token (Azure AD SAML), `custom:groups` claim |
| DynamoDB / S3 / STS / KMS / Secrets Manager | LocalStack (`:4566`) | Real AWS |
| EMR / SageMaker / Snowflake | In-process `*_MOCK_MODE=true` | Real services |
| Tenant provisioning | `TENANT_PROVISIONING_MOCK_MODE=true` | direct boto3 via the dataplane runtime role |
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
