# ML Training Platform — Frontend

React 18 + TypeScript + Vite + Tailwind CSS frontend for a multi-tenant ML
training platform built for a regulated (banking) environment: job
submission and monitoring, experiment comparison, model registry, Model
Risk Management (MRM) governance review, and Snowflake data browsing —
with role-based UI gating that mirrors the backend's tenancy/role model.

This is the **frontend-only** repo. The backend (FastAPI/DynamoDB) lives
in a separate repo and is talked to purely over HTTP
(`VITE_API_BASE_URL`).

- **Stack**: React 18 · TypeScript · Vite · Tailwind CSS
- **Auth**: MSAL (Azure Entra ID, PKCE) in production; a **demo mode**
  (`VITE_DEMO_MODE=true`) shows a role-selector instead of the Microsoft
  SSO button for local dev — cosmetic only, the real role always comes
  from the backend's `GET /auth/me`
- **Deploy target**: AWS ECS (Fargate) — static build served by nginx
- **Local dev**: no Docker required — plain `npm install && npm run dev`

---

## Quick start — local dev (no Docker)

**Prerequisites**: Node 20. **Start the backend project first** (separate
repo — see its own README) so this frontend has something to call.

```bash
git clone <this-repo-url> ml-training-platform-frontend
cd ml-training-platform-frontend

npm install
npm run dev
```

`npm run dev` runs `scripts/dev.mjs`, which checks the backend's
`/health` endpoint before starting Vite — if the backend isn't up yet,
you get a clear error telling you to start it, instead of a wall of CORS/
network errors in the browser console.

Open **http://localhost:3000**. In demo mode you're greeted with a role
selector instead of a Microsoft login — this is purely cosmetic; the
actual role always comes from the backend's `DEV_USER_ROLE` (see the
backend project's README to change it).

| Service  | URL                          |
|----------|------------------------------|
| Frontend | http://localhost:3000        |
| Backend  | http://localhost:8000 (separate repo) |

### Alternative: standalone Docker

```bash
docker build -t ml-platform-frontend .
docker run -p 3000:3000 -e VITE_API_BASE_URL=http://host.docker.internal:8000 ml-platform-frontend
```

There is no `docker-compose.yml` in this repo (that lived in the original
monorepo alongside the backend and LocalStack). `npm run dev` above is
the supported local-dev path.

---

## Troubleshooting

- **"Can't reach the backend" on startup** — the backend project isn't
  running yet, or `VITE_API_BASE_URL` in `.env` doesn't match the port it
  bound to. Start the backend first (its own `python scripts/dev.py`
  prints the URL it's listening on).
- **CORS errors in the browser console** — the backend's
  `CORS_ALLOWED_ORIGINS` must include this frontend's actual origin
  (`http://localhost:3000` by default). Check the *backend* project's
  `.env`, not anything here.
- **Testing a different role** — the login page's role selector is
  cosmetic. Change `DEV_USER_ROLE` in the *backend* project's `.env` and
  restart its dev process; this repo has no role state of its own.

---

## Role-based UI gating

Actual authorization is enforced by the backend — this frontend gates the
UI to match it, so a user never sees a control that would just 403, but
the UI gate is a convenience, not the security boundary.

- **Platform Admin** — manage tenants, group mappings; view everything.
- **Tenant Admin** — manage own tenant; view jobs/experiments/models; no
  job submission or model registration.
- **Data Scientist** — the only role with "Submit Job" / "Register
  Model"; has its own landing dashboard.
- **MRM** — read-only across all tenants; the only role with governance
  approve/reject actions.

`useTenantContext()` (`src/hooks/useTenantContext.ts`) is the single
source of these flags (`isPlatformAdmin`, `isMRM`, `isTenantAdmin`,
`isDataScientist`, `canSubmitJobs`, `isReadOnly`) — every gated action in
the app should read from it rather than re-deriving role logic locally.

---

## Moving from local dev to production — checklist

- [ ] `VITE_DEMO_MODE=false`.
- [ ] Fill in `VITE_ENTRA_TENANT_ID`, `VITE_ENTRA_CLIENT_ID` (MSAL config
      — must match the backend's Entra App Registration).
- [ ] `VITE_API_BASE_URL` → the deployed backend's real URL (behind the
      ALB, not `localhost`).
- [ ] Confirm the backend's `CORS_ALLOWED_ORIGINS` includes this
      frontend's real deployed origin.

---

## ECS deployment

```bash
ACCOUNT_ID=<your-account-id>
REGION=us-east-1
ECR=${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com

aws ecr create-repository --repository-name ml-platform-frontend
aws ecr get-login-password --region ${REGION} \
  | docker login --username AWS --password-stdin ${ECR}

docker build -t ${ECR}/ml-platform-frontend:latest .
docker push ${ECR}/ml-platform-frontend:latest

aws ecs register-task-definition --cli-input-json file://infrastructure/ecs/task-definition-frontend.json

# First deploy (fill subnet/SG/target-group placeholders first):
aws ecs create-service --cli-input-json file://infrastructure/ecs/ecs-service-frontend.json
# Subsequent deploys:
aws ecs update-service --cluster ml-platform-cluster --service ml-platform-frontend --force-new-deployment
```

Replace the `ACCOUNT_ID`, subnet, security-group, and target-group
placeholders in `infrastructure/ecs/*.json` before applying. The ALB
should forward everything except `/api/*` to this service's target group
(port 80, `ip` target type for Fargate awsvpc) — see the backend
project's README for the `/api/*` side of that routing.

`Dockerfile` here is a multi-stage build: `build` stage runs
`npm ci && npm run build`, final stage is `nginx:alpine` serving `/dist`
with SPA-fallback routing, gzip, and cache headers for hashed assets
(`nginx.conf`).

---

## Repository layout

```
.
├── README.md                       # this file
├── .env.example                    # copy to .env
├── package.json
├── Dockerfile                      # build → nginx prod serve
├── nginx.conf                      # SPA fallback, gzip, asset caching
├── vite.config.ts, tsconfig.json, tailwind.config.ts
├── scripts/
│   └── dev.mjs                     # backend-readiness check + Vite (no Docker)
├── public/
│   └── truist-logo.svg
├── src/
│   ├── main.tsx, App.tsx           # router, role-gated routes
│   ├── auth/                       # MSAL config, AuthContext, route guard
│   ├── api/                       # one module per backend resource
│   ├── hooks/                      # useTenantContext, usePolling, useSnowflake
│   ├── types/platform.ts           # mirrors backend Pydantic models
│   ├── components/                 # layout, shared UI, jobs, snowflake, s3
│   └── pages/                      # one per route (admin, tenant, workspace, governance, snowflake, audit)
└── infrastructure/
    └── ecs/
        ├── task-definition-frontend.json
        └── ecs-service-frontend.json
```
