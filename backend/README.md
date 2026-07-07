# ML Training Platform — Backend

FastAPI (async, Python 3.12) backend for a multi-tenant ML training
platform built for a regulated (banking) environment: job submission to
EMR Serverless/SageMaker Training, experiment tracking, model registry,
Model Risk Management (MRM) governance, and Snowflake data access (OAuth,
per-user identity) — all with tenancy and roles derived entirely from
Azure Entra ID group membership.

This is the **backend-only** repo. The frontend (React/TS/Vite) lives in
a separate repo and talks to this one purely over HTTP.

- **Stack**: Python 3.12 · FastAPI (async) · DynamoDB single-table design (boto3) · Pydantic v2
- **Auth**: Azure Entra ID (OIDC/OAuth2 PKCE); role + tenant resolved from
  the `groups` claim against a `GroupMapping` table, re-resolved on every
  request in prod — never cached, never manually assigned
- **Data**: Snowflake via OAuth token-exchange (per-user tokens, KMS-encrypted at rest)
- **Compute**: EMR Serverless / SageMaker Training (launch targets only — never provisioned by this app)
- **Deploy target**: AWS ECS (Fargate) — no Lambda, no Step Functions
- **Local dev**: no Docker required — a Python venv + `moto`'s standalone
  server emulate DynamoDB/S3/KMS/Secrets Manager

---

## Quick start — local dev (no Docker)

**Prerequisites**: Python 3.12. Nothing else — `moto[server]` (installed
below) provides the AWS emulation in pure Python.

```bash
git clone <this-repo-url> ml-training-platform-backend
cd ml-training-platform-backend

python -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows

pip install -r requirements.txt -r requirements-dev.txt

python scripts/dev.py
```

`scripts/dev.py` copies `.env.example` → `.env` on first run, starts
`python -m moto.server` on port 5000 (replaces DynamoDB/S3/KMS/Secrets
Manager — no LocalStack, no Docker, no JVM), waits for it to be ready,
runs the KMS setup + table creation + demo-seed scripts against it, then
starts `uvicorn --reload` on port 8000. Ctrl+C stops both together.

| Service     | URL                          |
|-------------|------------------------------|
| API         | http://localhost:8000        |
| API docs    | http://localhost:8000/docs   |
| moto server | http://localhost:5000        |

You are **already authenticated as Platform Admin** via `AUTH_MODE=dev` —
no Entra ID setup needed for local dev.

### Alternative: standalone Docker

```bash
docker build -t ml-platform-backend .
```

The `Dockerfile`'s `dev`/`prod` targets are self-contained and will
build/run on their own, but a lone container has nothing to talk to for
DynamoDB/S3/KMS unless you either point it at real AWS (fill in the
credentials, leave every `*_ENDPOINT_URL` blank) or run `moto_server`
alongside it yourself and pass its address via `*_ENDPOINT_URL`. There is
no `docker-compose.yml` in this repo (that lived in the original monorepo
alongside the frontend and LocalStack) — **`scripts/dev.py` above is the
supported local-dev path.**

---

## How local dev auth works

- **`AUTH_MODE=dev`**: skips JWT validation entirely. `get_current_user`
  synthesizes a `CurrentUser` from `DEV_USER_ID`, `DEV_USER_EMAIL`,
  `DEV_USER_NAME`, `DEV_USER_ROLE`, `DEV_USER_TENANT_ID` — no DynamoDB
  `GroupMapping` lookup happens. Strictly gated on `AUTH_MODE == "dev"`,
  never active in prod.

### Switch roles

| Role           | `DEV_USER_ROLE`  | `DEV_USER_TENANT_ID`      |
|----------------|------------------|---------------------------|
| Platform Admin | `PlatformAdmin`  | *(leave blank)*           |
| Tenant Admin   | `TenantAdmin`    | `tenant-risk-analytics`   |
| Data Scientist | `DataScientist`  | `tenant-fraud-detection`  |
| MRM            | `MRM`            | *(leave blank)*           |

Edit `.env`, then **stop `scripts/dev.py` (Ctrl+C) and re-run it** —
environment variables are read once at process startup, so a plain file
edit alone has no effect until the process restarts.

---

## Local development workflow

```bash
# Smoke-test every major endpoint (needs curl + jq)
../scripts/test-api.sh          # or wherever you keep it — see note below

# Reset demo data to a clean seeded state (moto_server must still be running)
python scripts/reset_local_db.py

# Interactive API (FastAPI Swagger UI — fully usable in AUTH_MODE=dev)
open http://localhost:8000/docs
```

> If you split off from the original monorepo, bring `scripts/test-api.sh`
> along too, or just exercise the API directly via `/docs`.

---

## Troubleshooting

- **"Address already in use" on port 5000 (moto_server) or 8000
  (uvicorn)** — something from a previous run is still alive; find and
  stop it rather than picking a different port (every `*_ENDPOINT_URL` in
  `.env` is hardcoded to port 5000 by default).
- **`ModuleNotFoundError: moto`** — `requirements-dev.txt` wasn't
  installed: `pip install -r requirements.txt -r requirements-dev.txt`.
- **Edited `DEV_USER_ROLE` but the API still resolves the old role** —
  restart `scripts/dev.py` (Ctrl+C, then re-run); env vars are read once
  at startup.
- **`seed_demo_data.py` fails partway through** — it's idempotent per
  item, safe to re-run.

---

## Entra ID App Registration setup (production only)

Not needed locally. In production, tenancy and role are derived from the
Entra `groups` claim — there are **no App Roles**.

1. **Register the API application** in Entra ID.
2. **Expose an API** with scopes `ml-platform.read` and `ml-platform.write`.
   Application ID URI `api://ml-training-platform` (matches `ENTRA_AUDIENCE`).
3. **Token configuration → optional claims** (ID + access token): `email`,
   `given_name`, `family_name`, `oid`, `tid`, and **`groups`** (critical —
   source of truth for role/tenant).
4. **Token configuration → Groups claim**: enable **Security groups**.
5. **Group overage**: tokens include at most **200 groups**; beyond that
   Entra emits a `_claim_names`/`_claim_sources` overage pointer instead —
   `oidc.py` handles this via a Microsoft Graph API call.
6. **Map groups to roles/tenants** after deploy — via `POST /group-mappings`
   or the frontend's Group Mappings page (PlatformAdmin). Create Entra
   security groups such as `ML-PlatformAdmins`,
   `ML-RiskAnalytics-DataScientists`, `ML-FraudDetection-TenantAdmins`. To
   find a group's Object ID: **Azure Portal → Entra ID → Groups → select
   group → Overview → Object ID**.

Access changes take effect on the user's **next login** — no application
change required. Highest privilege wins on multiple group matches
(`PlatformAdmin > MRM > TenantAdmin > DataScientist`). No mapping found →
API returns **403**.

---

## Snowflake OAuth integration setup

Each user's Entra access token is exchanged for a Snowflake OAuth token
(RFC 8693 token-exchange), so jobs and queries run under the **submitting
user's** Snowflake identity, never a shared service account.

1. As **ACCOUNTADMIN**, run `scripts/setup_snowflake_integration.sql`. It
   creates `SECURITY INTEGRATION ml_platform_oauth` (Entra as trusted
   issuer), an `ML_PLATFORM_ROLE`, resource monitors, and warehouse
   grants, ending with `DESCRIBE SECURITY INTEGRATION ml_platform_oauth;`.
2. Copy the client ID/secret into `SNOWFLAKE_OAUTH_CLIENT_ID` /
   `SNOWFLAKE_OAUTH_CLIENT_SECRET` in `.env`.
3. Configure the Entra App Registration as a **trusted identity provider**
   in the Snowflake integration.
4. Test with `POST /snowflake/connect` using a real Entra token; confirm
   the returned `snowflakeUsername` matches the expected Entra UPN.

Tokens are KMS-encrypted (`KMS_SNOWFLAKE_KEY_ARN`) before caching in
`SnowflakeTokenCache` (DynamoDB TTL on `expiresAt`). Passed to EMR/
SageMaker jobs only as a Secrets Manager ARN (TTL-bound, deleted after the
job) — never as plaintext.

---

## Moving from local dev to production — checklist

- [ ] Real Entra ID App Registration with the `groups` claim enabled.
- [ ] `AUTH_MODE=prod`.
- [ ] Remove every `*_ENDPOINT_URL` (`DYNAMODB_ENDPOINT_URL`,
      `S3_ENDPOINT_URL`, `KMS_ENDPOINT_URL`, `SECRETS_MANAGER_ENDPOINT_URL`)
      — blank means real AWS.
- [ ] Disable all mock modes: `EMR_MOCK_MODE=false`,
      `SAGEMAKER_MOCK_MODE=false`, `SNOWFLAKE_MOCK_MODE=false`.
- [ ] Fill in `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_TOKEN_URL`,
      `SNOWFLAKE_OAUTH_CLIENT_ID`, `SNOWFLAKE_OAUTH_CLIENT_SECRET`.
- [ ] Create a real AWS KMS key and set `KMS_SNOWFLAKE_KEY_ARN`.
- [ ] Run `scripts/setup_snowflake_integration.sql` in Snowflake.
- [ ] Fill in real `EMR_SERVERLESS_APPLICATION_ID`, `SAGEMAKER_DOMAIN_ID`,
      `SAGEMAKER_EXECUTION_ROLE_ARN`.
- [ ] Provision an EMR Studio separately (this app never creates one) and
      set `EMR_STUDIO_ID` — a different resource from
      `EMR_SERVERLESS_APPLICATION_ID`.
- [ ] Create the DynamoDB table in real AWS (CloudFormation below, or
      `create_tables.py` with every `*_ENDPOINT_URL` unset).
- [ ] Create group mappings via `POST /group-mappings`.
- [ ] Add users to Entra security groups to grant access.

---

## AWS setup & ECS deployment

1. **DynamoDB table**:

   ```bash
   aws cloudformation deploy \
     --template-file infrastructure/dynamodb/tables.json \
     --stack-name ml-platform-dynamodb \
     --parameter-overrides TableName=ml-platform \
     --capabilities CAPABILITY_NAMED_IAM
   ```

   (or `python scripts/create_tables.py` with every `*_ENDPOINT_URL` unset)

2. **ECR repository**: `aws ecr create-repository --repository-name ml-platform-backend`
3. **ECS cluster**: `aws ecs create-cluster --cluster-name ml-platform-cluster`
4. **IAM roles**: an ECS execution role (pull from ECR, read SSM/Secrets,
   write CloudWatch Logs) and a task role with DynamoDB (table + GSIs),
   S3 (artifacts bucket), KMS (Snowflake key encrypt/decrypt), Secrets
   Manager (job-token prefix), EMR Serverless, SageMaker, STS.
5. **SSM Parameter Store / Secrets Manager**: create the parameters
   referenced by `infrastructure/ecs/task-definition-backend.json`'s
   `secrets[].valueFrom` under `/ml-platform/...`.
6. **Application Load Balancer**: HTTPS listener forwarding to this
   service's target group (port 8000, `ip` target type for Fargate
   awsvpc) — update the ARN in `infrastructure/ecs/ecs-service-backend.json`.

```bash
ACCOUNT_ID=<your-account-id>
REGION=us-east-1
ECR=${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com

aws ecr get-login-password --region ${REGION} \
  | docker login --username AWS --password-stdin ${ECR}

docker build -t ${ECR}/ml-platform-backend:latest .
docker push ${ECR}/ml-platform-backend:latest

aws ecs register-task-definition --cli-input-json file://infrastructure/ecs/task-definition-backend.json

# First deploy (fill subnet/SG/target-group placeholders first):
aws ecs create-service --cli-input-json file://infrastructure/ecs/ecs-service-backend.json
# Subsequent deploys:
aws ecs update-service --cluster ml-platform-cluster --service ml-platform-backend --force-new-deployment
```

Replace the `ACCOUNT_ID`, subnet, security-group, and target-group
placeholders in `infrastructure/ecs/*.json` before applying.

---

## Environment variables reference

| Variable | Description | Local default | Prod example |
|---|---|---|---|
| `ENTRA_TENANT_ID` | Entra directory (tenant) ID | *(blank)* | `11111111-2222-3333-4444-555555555555` |
| `ENTRA_CLIENT_ID` | App registration client ID | *(blank)* | `66666666-7777-8888-9999-000000000000` |
| `ENTRA_AUDIENCE` | Expected JWT audience | `api://ml-training-platform` | `api://ml-training-platform` |
| `AUTH_MODE` | `dev` bypass or `prod` JWT validation | `dev` | `prod` |
| `DEV_USER_ID` | Synthetic user id (dev only) | `dev-user-001` | *(unset)* |
| `DEV_USER_EMAIL` | Synthetic user email (dev only) | `dev@local.test` | *(unset)* |
| `DEV_USER_NAME` | Synthetic user name (dev only) | `Dev User` | *(unset)* |
| `DEV_USER_ROLE` | Synthetic user role (dev only) | `PlatformAdmin` | *(unset)* |
| `DEV_USER_TENANT_ID` | Synthetic user tenant (dev only) | `tenant-risk-analytics` | *(unset)* |
| `CORS_ALLOWED_ORIGINS` | Allowed browser origins (JSON array) | `["http://localhost:3000"]` | `["https://ml.truist.example"]` |
| `AWS_REGION` | AWS region | `us-east-1` | `us-east-1` |
| `AWS_ACCESS_KEY_ID` | AWS key (blank → instance profile / moto default) | *(blank)* | *(blank / instance profile)* |
| `AWS_SECRET_ACCESS_KEY` | AWS secret | *(blank)* | *(blank / instance profile)* |
| `DYNAMODB_TABLE_NAME` | Single-table name | `ml-platform` | `ml-platform` |
| `DYNAMODB_ENDPOINT_URL` | DynamoDB endpoint (blank → real AWS) | `http://localhost:5000` | *(blank)* |
| `S3_ENDPOINT_URL` | S3 endpoint (blank → real AWS) | `http://localhost:5000` | *(blank)* |
| `S3_ARTIFACTS_BUCKET` | Artifacts bucket | `ml-platform-artifacts` | `ml-platform-artifacts-prod` |
| `EMR_SERVERLESS_APPLICATION_ID` | EMR Serverless app id (job submission) | *(blank)* | `00fabc123def456` |
| `EMR_STUDIO_ID` | EMR Studio id (notebook workspace — provisioned separately) | *(blank)* | `es-abc123def456` |
| `EMR_MOCK_MODE` | Return fake EMR job runs / Studio URLs | `true` | `false` |
| `SAGEMAKER_EXECUTION_ROLE_ARN` | SageMaker execution role | *(blank)* | `arn:aws:iam::…:role/sm-exec` |
| `SAGEMAKER_DOMAIN_ID` | SageMaker Studio domain | *(blank)* | `d-abc123` |
| `SAGEMAKER_MOCK_MODE` | Return fake SageMaker jobs/URLs | `true` | `false` |
| `SNOWFLAKE_ACCOUNT` | Snowflake account identifier | *(blank)* | `myorg-myaccount` |
| `SNOWFLAKE_OAUTH_INTEGRATION_NAME` | Snowflake security integration | `ml_platform_oauth` | `ml_platform_oauth` |
| `SNOWFLAKE_TOKEN_URL` | Snowflake token-exchange endpoint | *(blank)* | `https://<acct>.snowflakecomputing.com/oauth/token-request` |
| `SNOWFLAKE_OAUTH_CLIENT_ID` | OAuth client id | *(blank)* | *(from DESCRIBE INTEGRATION)* |
| `SNOWFLAKE_OAUTH_CLIENT_SECRET` | OAuth client secret | *(blank)* | *(Secrets Manager)* |
| `SNOWFLAKE_DEFAULT_WAREHOUSE` | Default warehouse | `COMPUTE_WH` | `ML_WH` |
| `SNOWFLAKE_MOCK_MODE` | Return mock Snowflake data | `true` | `false` |
| `KMS_SNOWFLAKE_KEY_ARN` | KMS key for token encryption | *(blank → local alias)* | `arn:aws:kms:…:key/…` |
| `KMS_ENDPOINT_URL` | KMS endpoint (blank → real AWS) | `http://localhost:5000` | *(blank)* |
| `SECRETS_MANAGER_ENDPOINT_URL` | Secrets Manager endpoint | `http://localhost:5000` | *(blank)* |
| `SECRETS_MANAGER_JOB_TOKEN_PREFIX` | Prefix for per-job token secrets | `ml-platform/job-tokens/` | `ml-platform/job-tokens/` |

---

## API usage examples

In local dev (`AUTH_MODE=dev`) **no auth header is required**. Against
production, add `-H "Authorization: Bearer <entra-access-token>"`.

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

**Submit a training job** (EMR Serverless, reading from Snowflake — mock mode)

```bash
curl -s -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
        "name": "pd-model-nightly",
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

**Submit a governance review decision** (MRM / PlatformAdmin)

```bash
REVIEW_ID=$(curl -s -X POST http://localhost:8000/governance/reviews \
  -H "Content-Type: application/json" \
  -d '{ "modelId": "probability-of-default", "version": 1 }' | jq -r '.reviewId')

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

## Repository layout

```
.
├── README.md                       # this file
├── .env.example                    # copy to .env
├── requirements.txt                # prod deps
├── requirements-dev.txt            # + moto[server], local dev only
├── Dockerfile                      # base → dev → prod (non-root, healthcheck)
├── app/
│   ├── main.py, config.py, dependencies.py
│   ├── auth/                       # OIDC/JWT validation, models
│   ├── db/                         # boto3 client factory, domain models, repositories
│   ├── middleware/
│   ├── routers/                    # one per resource
│   └── services/                   # job dispatch, notebooks, audit, snowflake, feature store
├── scripts/
│   ├── dev.py                      # one-command local bring-up (no Docker)
│   ├── create_tables.py
│   ├── seed_demo_data.py
│   ├── reset_local_db.py
│   ├── setup_local_kms.py
│   └── setup_snowflake_integration.sql
└── infrastructure/
    ├── dynamodb/tables.json        # CloudFormation: single table + GSIs + TTL
    └── ecs/
        ├── task-definition-backend.json
        └── ecs-service-backend.json
```
