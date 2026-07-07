# Multi-Tenant ML Model Training Platform

A production-grade, multi-tenant machine-learning training platform built for a
regulated (banking) environment. Data scientists submit training jobs to **EMR
Serverless** or **SageMaker Training**, track experiments and model versions,
preview source data from **Snowflake** (OAuth, per-user identity), and route
models through a **Model Risk Management (MRM)** governance workflow — all with
tenancy and roles derived entirely from **Azure Entra ID** group membership.

- **Backend:** Python 3.12 · FastAPI (async) · DynamoDB single-table design (boto3)
- **Frontend:** React 18 · TypeScript · Vite · Tailwind CSS
- **Auth:** Azure Entra ID (OIDC / OAuth2 PKCE); role + tenant **derived from
  security-group names** (`myapp-{tenant}-{role}` convention) — nothing to
  administer in the app, and users with several groups can switch role/tenant
  from the topbar
- **Data:** Snowflake via OAuth token-exchange (per-user tokens, KMS-encrypted)
- **Compute:** EMR Serverless / SageMaker Training (launched from the portal)
- **Deploy target:** AWS ECS (Fargate) — no Lambda, no Step Functions
- **Local dev:** entire stack via `docker compose` + LocalStack + mock modes —
  **zero real AWS / Entra / Snowflake credentials required**

---

## Architecture

```
                               ┌────────────────────────────────────────┐
                               │            External providers          │
                               │                                        │
                               │   Azure Entra ID      Snowflake        │
                               │   (identity, groups)  (data, OAuth)    │
                               └───────▲───────────────────▲────────────┘
                                       │ OIDC/JWT          │ OAuth token-exchange
                                       │ (groups claim)    │ (per-user identity)
                                       │                   │
   ┌─────────┐   HTTPS      ┌──────────┴─────────┐   ┌─────┴──────────────┐
   │ Browser │ ───────────► │  Frontend (ECS)    │   │   Backend (ECS)    │
   │  (SPA)  │ ◄─────────── │  React + nginx :80 │   │  FastAPI :8000     │
   └─────────┘   REST/JSON  └──────────┬─────────┘   │  async, Pydantic v2│
                     │                 │  /api        └───┬────────┬───────┘
                     └─────────────────┘                  │        │
                                                          │        │ submit
                                          ┌───────────────▼──┐   ┌─▼───────────────────┐
                                          │   DynamoDB       │   │ EMR Serverless /    │
                                          │  single table    │   │ SageMaker Training  │
                                          │  + GSIs, TTL     │   │ (launch targets)    │
                                          └──────────────────┘   └─────────────────────┘
                                          KMS · Secrets Manager · S3 (artifacts)

   ── Local development (docker compose) ────────────────────────────────────────
   LocalStack replaces DynamoDB · S3 · STS · KMS · Secrets Manager.
   EMR / SageMaker / Snowflake are replaced by in-process MOCK modes.
   Entra ID is bypassed by AUTH_MODE=dev (synthetic user from env vars).
```

In local dev, everything inside the AWS boundary is emulated by **LocalStack**,
and EMR/SageMaker/Snowflake are served by **mock modes** in the backend, so the
full application runs on a laptop with no cloud accounts.

---

## Quick start — local dev

**Prerequisites:** Docker Desktop ≥ 24 (or Docker Engine ≥ 24) with the Compose
plugin. Nothing else — Python and Node run inside containers.

```bash
git clone <repo-url> ml-training-platform
cd ml-training-platform
./scripts/dev.sh        # builds, starts, seeds demo data, waits for health, prints URLs
```

Then open **http://localhost:3000**. You are **already logged in as Platform
Admin** via `AUTH_MODE=dev` — no Entra ID setup needed.

| Service    | URL                          |
|------------|------------------------------|
| Frontend   | http://localhost:3000        |
| Backend    | http://localhost:8000        |
| API docs   | http://localhost:8000/docs   |
| LocalStack | http://localhost:4566        |

`dev.sh` copies `.env.example` → `.env` on first run, brings up the stack with
`docker compose up --build -d`, waits for LocalStack and the backend to report
healthy, and prints a usage summary. The one-shot `dynamo-init` container sets up
the LocalStack KMS key, creates the DynamoDB table, and seeds demo data before
the backend starts.

> Windows note: run `./scripts/dev.sh` from **Git Bash** or **WSL**. From
> PowerShell you can instead run the underlying commands directly:
> `Copy-Item .env.example .env; docker compose up --build -d`.

---

## How local dev auth works

Local development bypasses real identity providers entirely.

- **`AUTH_MODE=dev` (backend):** skips JWT validation. `get_current_user`
  synthesizes a `CurrentUser` from `DEV_USER_ID`, `DEV_USER_EMAIL`,
  `DEV_USER_NAME`, `DEV_USER_ROLE`, and `DEV_USER_TENANT_ID` — no group-name
  resolution is performed. Optionally set `DEV_USER_MEMBERSHIPS` (comma-
  separated `Role:tenantId` pairs, e.g.
  `DataScientist:tenant-fraud-detection,TenantAdmin:tenant-risk-analytics`)
  to give the dev user extra memberships and exercise the topbar role/tenant
  switcher locally. This bypass is gated strictly on `AUTH_MODE == "dev"` and
  never activates in prod.
- **`VITE_DEMO_MODE=true` (frontend):** the login page shows a **role-selector
  dropdown** instead of the Microsoft SSO button. The selector is *purely
  visual* — it sets a `localStorage` key used for styling only. The authoritative
  role always comes from the backend synthetic user (i.e. `DEV_USER_ROLE`).

### Switch roles by editing `.env`

| Role           | `DEV_USER_ROLE`  | `DEV_USER_TENANT_ID`      |
|----------------|------------------|---------------------------|
| Platform Admin | `PlatformAdmin`  | *(leave blank)*           |
| Tenant Admin   | `TenantAdmin`    | `tenant-risk-analytics`   |
| Data Scientist | `DataScientist`  | `tenant-fraud-detection`  |
| MRM            | `MRM`            | *(leave blank)*           |

After editing `.env`, restart just the backend (no full rebuild needed):

```bash
docker compose restart backend
```

Then hard-refresh the browser (Ctrl/Cmd + Shift + R).

---

## Prerequisites

| Tool                          | Needed for                | Check                                   |
|-------------------------------|---------------------------|-----------------------------------------|
| Docker Desktop ≥ 24 / Engine  | Everything (local dev)    | `docker --version && docker compose version` |
| `curl` + `jq`                 | `scripts/test-api.sh`     | `curl --version && jq --version`        |
| AWS CLI                       | ECS deployment only       | `aws --version`                         |

**No Python or Node is required on the host** — both run inside containers.

---

## Local development workflow

```bash
# Logs (follow)
docker compose logs -f backend
docker compose logs -f frontend

# Interactive API (FastAPI Swagger UI — fully usable in AUTH_MODE=dev)
open http://localhost:8000/docs

# Smoke-test every major endpoint
./scripts/test-api.sh

# Reset demo data to a clean seeded state
docker compose exec backend python scripts/reset_local_db.py

# Backend unit tests / frontend type-check
docker compose exec backend pytest
docker compose exec frontend npm run type-check

# Stop (data persists in the localstack-data volume)
docker compose down

# Full clean (also removes the LocalStack data volume)
docker compose down -v
```

**Hot reload:**
- Backend reloads on any `.py` save (`uvicorn --reload` + bind mount `./backend:/app`).
- Frontend reloads on any `.ts/.tsx` save (Vite HMR + bind mount `./frontend:/app`;
  an anonymous volume preserves the container's `node_modules`).

---

## Switching demo roles without restarting the full stack

1. Edit `DEV_USER_ROLE` (and `DEV_USER_TENANT_ID` if the role is tenant-scoped)
   in `.env`.
2. `docker compose restart backend`
3. Hard-refresh the browser (Ctrl/Cmd + Shift + R).

The frontend role-selector dropdown is cosmetic only — it sets a `localStorage`
key that styles the UI. The real role is always the backend synthetic user
driven by `DEV_USER_ROLE`.

---

## Entra ID App Registration setup (production only)

Not needed locally. For production, tenancy and role are **derived from Entra
security-group NAMES** following a naming convention — there are no App Roles
and no mapping table to administer. Access is governed entirely by AD group
membership, which your IGA process already reviews and recertifies.

**The naming convention** (configurable — see `GROUP_NAME_*` env vars):

| Group name | Grants |
|---|---|
| `myapp-platform-admin` | PlatformAdmin (all tenants) |
| `myapp-platform-mrm` | MRM (read across all tenants) |
| `myapp-{tenantId}-tenantadmin` | TenantAdmin of that tenant |
| `myapp-{tenantId}-datascientist` | DataScientist in that tenant |

A group naming a tenant that doesn't exist as a Tenant record grants nothing.

> **Security precondition:** with name-based resolution, the group name IS
> the access grant. Creation of groups matching the convention MUST be
> reserved to your governed provisioning (IGA) process — confirm this with
> whoever owns AD group naming before going live.

Setup steps:

1. **Register the API application** in Entra ID.
2. **Expose an API** with two scopes: `ml-platform.read` and `ml-platform.write`.
   Use the Application ID URI `api://ml-training-platform` (matches
   `ENTRA_AUDIENCE`).
3. **Token configuration → optional claims** (ID + access token): `email`,
   `given_name`, `family_name`, `oid`, `tid`, and **`groups`**.
4. **Token configuration → Groups claim:** enable **Security groups**. If your
   groups are synced from on-prem AD, prefer emitting the claim as
   **sAMAccountName** — the token then carries names directly and no Graph
   call is needed at login. Cloud-only groups emit Object IDs; the backend
   resolves their names via Microsoft Graph (`directoryObjects/getByIds`,
   cached ~15 min).
5. **Microsoft Graph access** (needed for GUID claims and for users in >200
   groups, where Entra emits an overage pointer instead of a `groups` claim):
   a **client secret** on the app registration (`ENTRA_CLIENT_SECRET`) and
   the **GroupMember.Read.All** application permission with admin consent.
6. **Create the AD groups** per the convention and add users to them. That's
   the entire onboarding flow — there is nothing to configure in the app.

When a user's group membership changes in Entra, their access changes on their
**next login** — no application change required. A user in several
convention groups holds **all** of those memberships and can switch role/
tenant from the topbar; the default is the highest privilege (`PlatformAdmin >
MRM > TenantAdmin > DataScientist`). Switching is validated server-side on
every request against the freshly derived memberships — it can never grant
more than AD does. If no group matches the convention, the API returns
**403** and the UI shows a "No Access" page.

---

## Snowflake OAuth integration setup

The platform is an OAuth client against Snowflake, exchanging each user's Entra
access token for a Snowflake OAuth token (RFC 8693 token-exchange) so jobs and
queries run under the **submitting user's** Snowflake identity — not a shared
service account.

1. As **ACCOUNTADMIN**, run `backend/scripts/setup_snowflake_integration.sql`.
   It creates `SECURITY INTEGRATION ml_platform_oauth` (custom OAuth client, Entra
   as trusted issuer), an `ML_PLATFORM_ROLE`, resource monitors, and warehouse
   grants, and ends with `DESCRIBE SECURITY INTEGRATION ml_platform_oauth;`.
2. Copy the client ID/secret shown by `DESCRIBE SECURITY INTEGRATION` into
   `SNOWFLAKE_OAUTH_CLIENT_ID` / `SNOWFLAKE_OAUTH_CLIENT_SECRET` in `.env`.
3. Configure the Entra App Registration as a **trusted identity provider** in the
   Snowflake integration.
4. Test with `POST /snowflake/connect` using a real Entra token and confirm the
   returned `snowflakeUsername` matches the expected Entra UPN.

Tokens are encrypted with AWS KMS (`KMS_SNOWFLAKE_KEY_ARN`) before being cached
in the `SnowflakeTokenCache` items (auto-expired by DynamoDB TTL on `expiresAt`).
When passed to EMR/SageMaker jobs, they transit via AWS Secrets Manager (secret
ARN only, TTL-bound, deleted after the job) — never as plaintext env vars.

---

## Moving from local dev to production — checklist

- [ ] Create a real Entra ID App Registration with the `groups` claim enabled.
- [ ] Set `AUTH_MODE=prod` and `VITE_DEMO_MODE=false`.
- [ ] Remove the LocalStack endpoints: `DYNAMODB_ENDPOINT_URL`,
      `S3_ENDPOINT_URL`, `KMS_ENDPOINT_URL`, `SECRETS_MANAGER_ENDPOINT_URL`.
- [ ] Disable all mock modes: `EMR_MOCK_MODE=false`, `SAGEMAKER_MOCK_MODE=false`,
      `SNOWFLAKE_MOCK_MODE=false`.
- [ ] Fill in `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_TOKEN_URL`,
      `SNOWFLAKE_OAUTH_CLIENT_ID`, `SNOWFLAKE_OAUTH_CLIENT_SECRET`.
- [ ] Create a real AWS KMS key and set `KMS_SNOWFLAKE_KEY_ARN` (the local
      `setup_local_kms.py` step is replaced by real KMS provisioning).
- [ ] Run `setup_snowflake_integration.sql` in Snowflake.
- [ ] Set `TENANT_PROVISIONING_MOCK_MODE=false` and stand up the tenant
      provisioning pipeline: an EventBridge rule on
      `ml-platform.tenants / TenantProvisioningRequested` that runs your IaC
      tenant module (per-tenant EMR Serverless application with a
      `maximumCapacity` matching the tenant quota, per-tenant execution role
      scoped to `s3://<bucket>/<tenantId>/*`, S3 prefix) and reports back via
      `PUT /tenants/{id}/provisioning`. Job submission is rejected until a
      tenant's provisioning is `active`.
- [ ] Fill in `SAGEMAKER_DOMAIN_ID` and `SAGEMAKER_TRAINING_IMAGE` (execution
      roles and EMR applications are per-tenant — provisioned by the pipeline,
      not env vars).
- [ ] Provision an EMR Studio separately in **SSO auth mode** (AWS Console/
      IaC — this app never creates one) and set `EMR_STUDIO_URL`; the app
      deep-links into it so each user's own identity applies. Known MVP
      limitation: the Studio is platform-global while jobs are per-tenant
      (workspace S3 locations must be tenant-prefixed); per-tenant Studios
      are a later release.
- [ ] Set `PLATFORM_API_BASE_URL` so training jobs receive
      `ML_PLATFORM_API_URL` + a per-run token (via the job secret) and can
      log metrics back to their run.
- [ ] Create the DynamoDB table in real AWS (CloudFormation below, or
      `create_tables.py` with `DYNAMODB_ENDPOINT_URL` unset).
- [ ] Create Entra security groups per the naming convention
      (`myapp-platform-admin`, `myapp-{tenantId}-datascientist`, …) and add
      users — no in-app identity configuration exists. Set `GROUP_NAME_PATTERN`
      / `GROUP_NAME_PLATFORM_ADMIN` / `GROUP_NAME_MRM` if your firm's naming
      standard differs from the default.
- [ ] Confirm with your IGA/AD owners that creation of convention-matching
      group names is restricted to the governed process (the name IS the
      access grant).
- [ ] Add users to Entra security groups to grant platform access.

---

## AWS setup

1. **DynamoDB table** — deploy the single table with all GSIs and TTL:

   ```bash
   aws cloudformation deploy \
     --template-file infrastructure/dynamodb/tables.json \
     --stack-name ml-platform-dynamodb \
     --parameter-overrides TableName=ml-platform \
     --capabilities CAPABILITY_NAMED_IAM
   ```

   (Alternatively, run `backend/scripts/create_tables.py` with
   `DYNAMODB_ENDPOINT_URL` unset to target real AWS.)

2. **ECR repositories** — one per image:

   ```bash
   aws ecr create-repository --repository-name ml-platform-backend
   aws ecr create-repository --repository-name ml-platform-frontend
   ```

3. **ECS cluster:**

   ```bash
   aws ecs create-cluster --cluster-name ml-platform-cluster
   ```

4. **IAM roles** — an ECS **execution role** (pull from ECR, read SSM/Secrets,
   write CloudWatch Logs) and per-service **task roles**:
   - Backend task role: DynamoDB (single table + GSIs), S3 artifacts bucket, KMS
     (Snowflake key: encrypt/decrypt), Secrets Manager (job-token prefix),
     EMR Serverless, SageMaker, STS, EventBridge `events:PutEvents` (tenant
     provisioning requests).
   - Frontend task role: minimal (static serving only).

5. **SSM Parameter Store / Secrets Manager** — create the parameters referenced
   by the task definitions' `secrets[].valueFrom` under `/ml-platform/...` (Entra,
   Snowflake, EMR, SageMaker, KMS, CORS). Secrets (client secret) go in Secrets
   Manager; the rest in SSM.

6. **Application Load Balancer** — HTTPS listener; forward `/api/*` (or a
   dedicated hostname) to the **backend** target group (port 8000) and everything
   else to the **frontend** target group (port 80). Create both target groups
   (`ip` target type for Fargate awsvpc) and update the ARNs in
   `infrastructure/ecs/ecs-service-*.json`.

---

## ECS deployment steps

```bash
ACCOUNT_ID=<your-account-id>
REGION=us-east-1
ECR=${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com

# 1. Authenticate Docker to ECR
aws ecr get-login-password --region ${REGION} \
  | docker login --username AWS --password-stdin ${ECR}

# 2. Build & push the backend (prod target is the default)
docker build -t ${ECR}/ml-platform-backend:latest ./backend
docker push ${ECR}/ml-platform-backend:latest

# 3. Build & push the frontend (prod target is the default → nginx)
docker build -t ${ECR}/ml-platform-frontend:latest ./frontend
docker push ${ECR}/ml-platform-frontend:latest

# 4. Register the task definitions (replace ACCOUNT_ID placeholders first)
aws ecs register-task-definition --cli-input-json file://infrastructure/ecs/task-definition-backend.json
aws ecs register-task-definition --cli-input-json file://infrastructure/ecs/task-definition-frontend.json

# 5a. Create the services on first deploy (fill subnet/SG/target-group placeholders)
aws ecs create-service --cli-input-json file://infrastructure/ecs/ecs-service-backend.json
aws ecs create-service --cli-input-json file://infrastructure/ecs/ecs-service-frontend.json

# 5b. On subsequent deploys, roll the services to the new task definition
aws ecs update-service --cluster ml-platform-cluster --service ml-platform-backend  --force-new-deployment
aws ecs update-service --cluster ml-platform-cluster --service ml-platform-frontend --force-new-deployment
```

Before applying, replace the `ACCOUNT_ID`, subnet, security-group, and
target-group **placeholders** in the JSON files under `infrastructure/ecs/`.

---

## Environment variables reference

| Variable | Description | Local default | Prod example |
|---|---|---|---|
| `ENTRA_TENANT_ID` | Entra directory (tenant) ID | *(blank)* | `11111111-2222-3333-4444-555555555555` |
| `ENTRA_CLIENT_ID` | App registration client ID | *(blank)* | `66666666-7777-8888-9999-000000000000` |
| `ENTRA_CLIENT_SECRET` | Client secret for Graph group-overage lookups (Secrets Manager) | *(blank)* | *(Secrets Manager)* |
| `ENTRA_AUDIENCE` | Expected JWT audience | `api://ml-training-platform` | `api://ml-training-platform` |
| `AUTH_MODE` | `dev` bypass or `prod` JWT validation | `dev` | `prod` |
| `DEV_USER_ID` | Synthetic user id (dev only) | `dev-user-001` | *(unset)* |
| `DEV_USER_EMAIL` | Synthetic user email (dev only) | `dev@local.test` | *(unset)* |
| `DEV_USER_NAME` | Synthetic user name (dev only) | `Dev User` | *(unset)* |
| `DEV_USER_ROLE` | Synthetic user role (dev only) | `PlatformAdmin` | *(unset)* |
| `DEV_USER_TENANT_ID` | Synthetic user tenant (dev only) | `tenant-risk-analytics` | *(unset)* |
| `DEV_USER_MEMBERSHIPS` | Extra `Role:tenantId` pairs for the dev user (switcher demo) | *(blank)* | *(unset)* |
| `GROUP_NAME_PATTERN` | Regex (named captures `tenant`, `role`) parsing tenant-scoped group names | `^myapp-(?P<tenant>…)-(?P<role>…)$` | *(firm's standard)* |
| `GROUP_NAME_PLATFORM_ADMIN` | Group name granting PlatformAdmin | `myapp-platform-admin` | *(firm's standard)* |
| `GROUP_NAME_MRM` | Group name granting MRM | `myapp-platform-mrm` | *(firm's standard)* |
| `CORS_ALLOWED_ORIGINS` | Allowed browser origins (JSON array) | `["http://localhost:3000"]` | `["https://ml.truist.example"]` |
| `AWS_REGION` | AWS region | `us-east-1` | `us-east-1` |
| `AWS_ACCESS_KEY_ID` | AWS key (blank → instance profile) | `test` | *(blank / instance profile)* |
| `AWS_SECRET_ACCESS_KEY` | AWS secret | `test` | *(blank / instance profile)* |
| `DYNAMODB_TABLE_NAME` | Single-table name | `ml-platform` | `ml-platform` |
| `DYNAMODB_ENDPOINT_URL` | DynamoDB endpoint (blank → real AWS) | `http://localstack:4566` | *(blank)* |
| `S3_ENDPOINT_URL` | S3 endpoint (blank → real AWS) | `http://localstack:4566` | *(blank)* |
| `S3_ARTIFACTS_BUCKET` | Artifacts bucket | `ml-platform-artifacts` | `ml-platform-artifacts-prod` |
| `EMR_SERVERLESS_APPLICATION_ID` | DEPRECATED — EMR apps are per-tenant (`Tenant.emrApplicationId`); kept only as a fallback for legacy job records | *(blank)* | *(blank)* |
| `EMR_STUDIO_URL` | Access URL of the SSO-mode EMR Studio (provisioned separately; the app deep-links into it so each user's own identity applies) | *(blank)* | `https://es-….emrstudio-prod.us-east-1.amazonaws.com` |
| `RUN_TOKEN_TTL_HOURS` | Lifetime of per-run machine tokens minted at job submission | `26` | `26` |
| `PLATFORM_API_BASE_URL` | Public API base URL injected into jobs as `ML_PLATFORM_API_URL` | *(blank)* | `https://ml.truist.example` |
| `EMR_MOCK_MODE` | Return fake EMR job runs / Studio URLs | `true` | `false` |
| `SAGEMAKER_DOMAIN_ID` | SageMaker Studio domain | *(blank)* | `d-abc123` |
| `SAGEMAKER_TRAINING_IMAGE` | Training container image for SageMaker jobs | *(blank)* | `…dkr.ecr…/training:latest` |
| `TENANT_PROVISIONING_MOCK_MODE` | Self-provision mock tenant resources (local) vs EventBridge handoff to the IaC pipeline (prod) | `true` | `false` |
| `TENANT_PROVISIONING_EVENT_BUS` | EventBridge bus for provisioning requests | `default` | `default` |
| `SAGEMAKER_MOCK_MODE` | Return fake SageMaker jobs/URLs | `true` | `false` |
| `SNOWFLAKE_ACCOUNT` | Snowflake account identifier | *(blank)* | `myorg-myaccount` |
| `SNOWFLAKE_OAUTH_INTEGRATION_NAME` | Snowflake security integration | `ml_platform_oauth` | `ml_platform_oauth` |
| `SNOWFLAKE_TOKEN_URL` | Snowflake token-exchange endpoint | *(blank)* | `https://<acct>.snowflakecomputing.com/oauth/token-request` |
| `SNOWFLAKE_OAUTH_CLIENT_ID` | OAuth client id | *(blank)* | *(from DESCRIBE INTEGRATION)* |
| `SNOWFLAKE_OAUTH_CLIENT_SECRET` | OAuth client secret | *(blank)* | *(Secrets Manager)* |
| `SNOWFLAKE_DEFAULT_WAREHOUSE` | Default warehouse | `COMPUTE_WH` | `ML_WH` |
| `SNOWFLAKE_MOCK_MODE` | Return mock Snowflake data | `true` | `false` |
| `KMS_SNOWFLAKE_KEY_ARN` | KMS key for token encryption | *(blank → local alias)* | `arn:aws:kms:…:key/…` |
| `KMS_ENDPOINT_URL` | KMS endpoint (blank → real AWS) | `http://localstack:4566` | *(blank)* |
| `SECRETS_MANAGER_ENDPOINT_URL` | Secrets Manager endpoint | `http://localstack:4566` | *(blank)* |
| `SECRETS_MANAGER_JOB_TOKEN_PREFIX` | Prefix for per-job token secrets | `ml-platform/job-tokens/` | `ml-platform/job-tokens/` |
| `VITE_API_BASE_URL` | Backend base URL (frontend) | `http://localhost:8000` | `https://ml.truist.example` |
| `VITE_ENTRA_TENANT_ID` | Entra tenant for MSAL (frontend) | *(blank)* | `11111111-…` |
| `VITE_ENTRA_CLIENT_ID` | Entra client for MSAL (frontend) | *(blank)* | `66666666-…` |
| `VITE_DEMO_MODE` | Show role-selector instead of SSO | `true` | `false` |

---

## API usage examples

In local dev (`AUTH_MODE=dev`) **no auth header is required** — the backend
injects the synthetic user. Against production, add
`-H "Authorization: Bearer <entra-access-token>"`.

**Create a tenant** (PlatformAdmin)

```bash
curl -s -X POST http://localhost:8000/tenants \
  -H "Content-Type: application/json" \
  -d '{
        "name": "Wholesale Credit",
        "allowedFrameworks": ["pytorch", "xgboost"],
        "computeQuotaVcpuHours": 5000
      }' | jq
```

**List jobs** (scoped automatically to the caller's tenant unless PlatformAdmin)

```bash
curl -s "http://localhost:8000/jobs?status=running" | jq
```

**Submit a training job** (EMR Serverless, reading from Snowflake — mock mode)

```bash
curl -s -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
        "name": "pd-model-nightly",
        "tenantId": "tenant-risk-analytics",
        "computeType": "emr_serverless",
        "framework": "xgboost",
        "entryPointScript": "s3://ml-platform-artifacts/scripts/train.py",
        "s3InputPath": "s3://ml-platform-artifacts/input/",
        "instanceType": "ml.m5.xlarge",
        "instanceCount": 2,
        "hyperparameters": { "max_depth": "6", "eta": "0.3", "num_round": "200" },
        "snowflakeDatabase": "PROD_DB",
        "snowflakeSchema": "ML_FEATURES",
        "snowflakeWarehouse": "COMPUTE_WH"
      }' | jq
```

**Register a model version** from a completed run

```bash
curl -s -X POST http://localhost:8000/models \
  -H "Content-Type: application/json" \
  -d '{
        "name": "probability-of-default",
        "tenantId": "tenant-risk-analytics",
        "framework": "xgboost",
        "artifactUri": "s3://ml-platform-artifacts/models/pd/1/",
        "description": "PD model v1 from nightly run",
        "runId": "run-0001"
      }' | jq
```

**Submit a governance review decision** (MRM / PlatformAdmin)

```bash
# Create a review for a model version
REVIEW_ID=$(curl -s -X POST http://localhost:8000/governance/reviews \
  -H "Content-Type: application/json" \
  -d '{
        "modelId": "<modelId from the registration response>",
        "modelName": "probability-of-default",
        "modelVersion": 1,
        "tenantId": "tenant-risk-analytics"
      }' | jq -r '.reviewId')

# Submit the decision
curl -s -X PUT "http://localhost:8000/governance/reviews/${REVIEW_ID}" \
  -H "Content-Type: application/json" \
  -d '{
        "decision": "approved",
        "comments": "Meets SR 11-7 documentation and validation standards.",
        "conditions": "Re-validate within 12 months."
      }' | jq
```

Explore every endpoint interactively at **http://localhost:8000/docs**.

---

## Repository layout (infrastructure & tooling)

```
.
├── README.md                       # this file
├── .env.example                    # copy to .env; single source of config for the stack
├── docker-compose.yml              # full local stack (localstack, init, backend, frontend)
├── scripts/
│   ├── dev.sh                      # one-command local bring-up
│   └── test-api.sh                 # curl+jq smoke tests for the backend
├── backend/
│   └── Dockerfile                  # base → dev → prod (non-root, healthcheck)
├── frontend/
│   ├── Dockerfile                  # base → dev → build → prod (nginx)
│   └── nginx.conf                  # SPA fallback, gzip, asset caching
└── infrastructure/
    ├── dynamodb/
    │   └── tables.json             # CloudFormation: single table + 3 overloaded GSIs + TTL
    └── ecs/
        ├── task-definition-backend.json
        ├── task-definition-frontend.json
        ├── ecs-service-backend.json
        └── ecs-service-frontend.json
```

The `backend/app/**`, `backend/scripts/**`, `backend/requirements.txt`, and
`frontend/src/**` application sources are maintained alongside this
infrastructure and are built/served by the Dockerfiles above.
