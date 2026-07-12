# Multi-Tenant ML Training Platform (mltpui)

FastAPI backend + React SPA for multi-tenant ML model training with MRM governance.

## Layout
- `backend/` — FastAPI (Pydantic v2, boto3), DynamoDB single-table. Routers in `backend/app/routers/`, repos in `backend/app/db/`, services in `backend/app/services/`.
- `frontend/` — React 18 + Vite + Tailwind + react-router v6. Pages in `frontend/src/pages/{admin,tenant,workspace,governance,snowflake,audit,features}/`, role-gated routes in `frontend/src/App.tsx`.
- `backend/iac/`, `frontend/iac/`, `emr-studio/iac/` — Terraform modules (ECS Fargate, EMR Studio).
- `scripts/dev.sh` — one-command local bring-up (moto/LocalStack, AUTH_MODE=dev synthetic users).

## Commands
- Local dev: `./scripts/dev.sh` (backend :8000, frontend :5173)
- Frontend: `cd frontend && npm run dev` / `npm run build` / `npm run type-check`
- Backend deps: `backend/requirements.txt` (+ `-dev.txt` for moto)

## Key conventions
- Auth: Azure Entra ID OIDC; roles derived from group names `myapp-{tenant}-{role}`. Roles: PlatformAdmin, TenantAdmin, DataScientist, MRM. `AUTH_MODE=dev` bypasses with synthetic user (DEV_USER_* env vars).
- Tenancy: every backend query is tenant-scoped via `CurrentUser` (see `backend/app/auth/models.py`, `dependencies.py`). Never bypass tenant scoping.
- DynamoDB: single-table design with GSIs + TTL; repos own all item shapes.
- Snowflake: per-user OAuth token exchange (RFC 8693); tokens KMS-encrypted in DynamoDB, handed to jobs via Secrets Manager TTL secrets.
- Control-plane / dataplane account split lives in the companion `tmt-dataplane` repo.
