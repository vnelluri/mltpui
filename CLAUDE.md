# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Multi-Tenant ML Training Platform (mltpui)

FastAPI backend + React SPA for multi-tenant ML model training with MRM governance.

## Layout
- `backend/` — FastAPI (Pydantic v2, boto3), DynamoDB single-table. Routers in `backend/app/routers/`, repos in `backend/app/db/`, services in `backend/app/services/`.
- `frontend/` — React 18 + Vite + Tailwind + react-router v6. Pages in `frontend/src/pages/{admin,tenant,workspace,governance,snowflake,audit,features}/`, role-gated routes in `frontend/src/App.tsx`.
- `backend/iac/`, `frontend/iac/`, `emr-studio/iac/` — Terraform modules (ECS Fargate, EMR Studio).

## Commands
Local dev runs entirely in Docker (LocalStack + backend + frontend) — no host Python/Node needed:
- Bring-up: `./scripts/dev.sh` (backend :8000, frontend :5173; creates `.env` from `.env.example` on first run)
- Logs: `docker compose logs -f backend` (or `frontend`)
- Smoke-test API: `./scripts/test-api.sh` (curl+jq against :8000; no auth headers needed in dev)
- Type-check frontend: `docker compose exec frontend npm run type-check`
- Reset demo data: `docker compose exec backend python scripts/reset_local_db.py`
- Stop: `docker compose down` (add `-v` to also wipe LocalStack data)
- Hot reload is automatic (uvicorn --reload, Vite) via bind mounts.
- No backend test suite yet; `scripts/test-api.sh` is the current check.

## Key conventions
- Auth: Azure Entra ID OIDC; roles derived from group names `myapp-{tenant}-{role}`. Roles: PlatformAdmin, TenantAdmin, DataScientist, MRM. `AUTH_MODE=dev` bypasses with a synthetic user from `DEV_USER_*` env vars.
- Switching dev roles: edit `DEV_USER_ROLE` (and `DEV_USER_TENANT_ID`) in `.env`, then `docker compose restart backend`. The frontend role dropdown is cosmetic; the backend synthetic user is the real role.
- Tenancy: every backend query is tenant-scoped via `CurrentUser` (see `backend/app/auth/models.py`, `dependencies.py`). Never bypass tenant scoping.
- DynamoDB: single-table design with GSIs + TTL; repos own all item shapes.
- Snowflake: per-user OAuth token exchange (RFC 8693); tokens KMS-encrypted in DynamoDB, handed to jobs via Secrets Manager TTL secrets.
- Control-plane / dataplane account split lives in the companion `tmt-dataplane` repo.
