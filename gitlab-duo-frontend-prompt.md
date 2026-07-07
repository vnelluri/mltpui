# Prompt: ML Training Platform — Frontend Project (GitLab Duo edition)

## How to use this document

This is **project 2 of 2** — the frontend only. Project 1 is the backend
(separate prompt file, separate GitLab repo) — build and run that first;
this project has nothing to talk to otherwise (`VITE_API_BASE_URL` points
at it over plain HTTP, `http://localhost:8000` locally).

> **Sequencing matters, especially if you're driving both repos from the
> same GitLab Duo agent/session.** Don't generate both projects in
> parallel from their two spec documents and hope they agree with each
> other. Build the backend repo first, actually run it
> (`python scripts/dev.py`), and get it through its own verification
> checklist — *then* generate this frontend against the real, running
> backend. A spec describes intent; the actual generated code is what has
> to match byte-for-byte (exact field names, exact enum values, whatever
> `http://localhost:8000/docs` actually says). If the same agent session
> spans both repos, that's a real advantage — it can check the frontend
> it's writing against the backend it already built and ran, instead of
> against the backend spec's description of itself. Use that advantage
> rather than generating both blind.

**Prerequisite you already have: a Truist component library prompt.**
This spec is written in terms of generic component names (`Button`,
`Card`, `Modal`, `DataTable`, `Field`/`Input`/`Select`/`Textarea`,
`StatusBadge`, layout shell) because that's what a from-scratch build
produced. **Do not build a generic Tailwind component kit from scratch
here** — hand GitLab Duo both this document and your existing Truist
components prompt together, and instruct it to map every generic
component name below onto the real equivalent from that library (props,
naming, and styling all deferred to the Truist components spec; this
document only describes *which* components are needed, in what shape of
data, and how they're wired to pages/routes/API calls). Where this doc
says "Button variant=danger", read it as "whatever your Truist library's
destructive-action button is."

**GitLab Duo Chat**: work through this file-by-file — types → api layer →
hooks → layout shell → pages, roughly in that order, one prompt turn per
group of related files. **GitLab Duo Workflow / agentic mode**: paste the
whole document as one task alongside the Truist components prompt.

**No Docker.** Local dev is just `npm install && npm run dev` — see §4.
There is nothing about this frontend that ever needed Docker except
building a deployable container image, which (like the backend) happens
in GitLab CI, not on a developer's machine.

---

## 0. Lessons from a working build of this exact frontend

1. **Every list API call must be typed against the same paginated
   envelope the backend actually returns**: `{items: T[], total: number,
   page: number, pageSize: number}`. A backend endpoint that returns a
   bare array while the frontend's shared API layer assumes the envelope
   produces a `Cannot read properties of undefined (reading 'length')`
   crash the first time that specific page loads. If a backend endpoint
   ever returns a flat array on purpose (e.g. a simple string list like
   "available databases"), handle both shapes defensively:
   `Array.isArray(data) ? data : data.someKey`.
2. **UI role-gating (hiding a button) is not authorization — it's a
   convenience.** The backend project enforces the actual boundary
   (§0.1 there). Still gate the UI to match exactly what the backend
   allows, so a user never sees a control that will just 403 — but don't
   let "the button is hidden" be the reason a mutating action feels safe
   to leave ungated in a modal that's reachable by a read-only role. When
   in doubt, check: does every actionable button in a page reachable by
   MRM (or any read-only-by-design role) actually check `isReadOnly`
   before rendering?
3. **When a modal/page has two independent async operations sharing one
   error state, a failure in one silently corrupts the display of the
   other.** E.g. a page that fetches a list (rendered via a shared table
   component with its own `error`/`onRetry` props) and *also* opens a
   detail modal that can fail its own fetch — if both paths call the same
   `setError`, a failed detail-modal fetch can make the *list* look
   broken (or vice versa), and worse, if the failure path doesn't clear a
   loading flag correctly, a spinner can spin forever instead of ever
   showing the error. Use separate error state per independent async
   flow (e.g. `listError` vs `detailError`), and double check every
   "loading OR no-data-yet" conditional actually has a reachable exit when
   the fetch fails, not just when it succeeds.
4. **Match the backend's run-status vocabulary exactly.** If the backend
   syncs an `ExperimentRun`'s status from the `TrainingJob` that produced
   it, the frontend's run-status type must be the same enum as job
   status (`queued | running | succeeded | failed | cancelled`) — not a
   narrower, differently-named set invented independently on the
   frontend side. Define it as a type alias of the job-status type, not a
   parallel literal union.
5. **A destructive, wide-blast-radius action needs a confirmation
   dialog; a low-stakes or purely-restorative one doesn't.** E.g.
   suspending a tenant (blocks every user in it) warrants a confirm
   dialog; cancelling a single job or reactivating a suspended tenant
   generally doesn't. Use judgement per-action rather than applying one
   rule everywhere — but do apply *some* rule consistently, so it's
   predictable which actions ask first.
6. **A "coming soon" affordance for a not-yet-built integration should be
   visually present but genuinely inert** — disabled, a small "Soon"
   badge, a tooltip explaining what it will do — not wired to any state,
   not a button that silently does nothing on click with no visual
   feedback that it's intentionally inactive.

---

## 1. Context

- Talks to the backend project (separate repo) over HTTP —
  `VITE_API_BASE_URL`, default `http://localhost:8000` for local dev.
- Auth: MSAL (Entra ID PKCE) in prod; a local **demo mode**
  (`VITE_DEMO_MODE=true`) that shows a role-selector instead of the
  Microsoft SSO button — purely cosmetic, the real role always comes from
  the backend's `GET /auth/me` (never trust client-decoded token claims
  for anything but display).
- **React 18 + TypeScript + Vite + Tailwind CSS**, with the Truist
  component library layered on top per the note above. All Tailwind
  classes present as literal strings (no dynamic class construction).
- No placeholders — every page fully implemented against real API calls
  (against the backend project's mock modes locally, so nothing is
  faked *again* on the frontend side).

## 2. Roles (for UI gating — actual enforcement lives in the backend project)

- **Platform Admin** — manage tenants, group mappings; view everything.
- **Tenant Admin** — manage own tenant's users/settings; view jobs/
  experiments/models within tenant; cannot submit jobs or register models.
- **Data Scientist** — the only role with "Submit Job" and "Register
  Model" actions; has its own landing dashboard.
- **MRM** — read-only across all tenants' models/experiments; the only
  role with governance approve/reject actions.

---

## 3. Frontend structure

```
frontend/
├── src/
│   ├── main.tsx, App.tsx            # router, role-gated routes
│   ├── auth/                        # MSAL config, AuthContext (GET /auth/me is authoritative), route guard
│   ├── api/                         # one thin module per resource; every list call typed Paginated<T> (§0.1)
│   ├── hooks/                       # usePolling, useTenantContext (role booleans incl. isReadOnly), useSnowflake
│   ├── types/platform.ts            # mirrors every backend Pydantic model field-for-field, camelCase
│   ├── components/
│   │   ├── layout/                  # sidebar (role-aware nav), topbar — via Truist shell components
│   │   ├── jobs/JobSubmitForm.tsx   # the 7-step wizard, see below
│   │   ├── snowflake/               # connect banner, table browser, query editor
│   │   ├── s3/S3Browser.tsx         # folder breadcrumb nav + file picker, mirrors the Snowflake browser's UX
│   │   └── features/                # optional Feature Store preview components (§3.6)
│   └── pages/                       # one per route, listed below
```

### Pages and their landing roles

- `LoginPage`, `UnauthorizedPage`, `NoAccessPage` (no group mapping found
  → explain and point at Group Mappings/Entra admin).
- **Admin** (Platform Admin): `AdminDashboard`, `TenantsPage` (list +
  create + **suspend needs a confirm dialog**, §0.5), `TenantDetailPage`,
  `GroupMappingsPage` (CRUD + helper text on finding an Entra group
  Object ID).
- **Tenant** (Tenant Admin): `TenantDashboard`, `TenantSettingsPage`.
- **Workspace** (shared, role-gated per action not per page):
  `DataScientistDashboard` (Data Scientist's landing page — stat tiles
  for their own jobs/experiments/models, a recent-jobs list, a
  recent-experiments list, "Submit Job" shortcut), `ExperimentsPage` +
  `ExperimentDetailPage` (side-by-side run comparison, highlight best
  value per metric column — lower-is-better heuristic for names
  containing "loss"/"psi"/"error", higher-is-better otherwise),
  `JobsPage` (polls every 5s, cancel action, a link from each job to its
  linked experiment run), `SubmitJobPage` (the wizard, below),
  `ModelsPage` (register — Data Scientist only; stage transition —
  Tenant Admin; model card viewer), `NotebookPage` (two launch cards,
  active-sessions list).
- **Governance** (MRM landing + Platform Admin): `GovernanceDashboard`
  (stat tiles: pending/approved/rejected/production-model counts, two
  "awaiting review" / "recently decided" lists), `ReviewQueuePage`,
  `ReviewDetailPage` (rendered model card, approve/reject with required
  comment, fields disabled for non-MRM viewers).
- **Snowflake**: connection banner (three states: connected/not-
  connected/expired, polled every 60s), table browser, query editor.
- **Feature Store** (optional preview, §3.6): list + create (Data
  Scientist only) + detail with batch/real-time preview + materialize
  (hidden for MRM per §0.2).
- **Audit**: filterable event log (Platform Admin all, Tenant Admin own
  tenant).

### Job submission wizard — 7 steps

1. Compute type (EMR Serverless / SageMaker) — visual cards.
2. Framework (pytorch/tensorflow/sklearn/xgboost) — visual cards.
3. Data source — three tabs: **Snowflake** (connect banner → table
   browser → preview → optional custom-SQL override), **S3** (real
   folder browser, §0 backend note — breadcrumb navigation, click to
   select a file/folder, manual-path override field kept editable), and a
   **disabled "Feature Store" tab** with a "Soon" badge and a tooltip
   explaining what it will eventually do (§0.6) — purely a roadmap
   signal, not wired to any state.
4. Script (entry point S3 path, output S3 path).
5. Resources (instance type/count/volume; EMR also: driver/executor
   memory, max executors — these must actually flow into the submitted
   payload, not just be collected and discarded).
6. Hyperparameters (dynamic key-value editor).
7. Review and submit — full config summary; warn if the Snowflake token
   will expire before an estimated completion time.

### 3.6 Feature Store preview components (optional — only if the backend
project built the `/feature-store` endpoints)

Label this clearly as a preview everywhere it appears — a small "Preview"
badge next to the page title, and an inline banner explaining: batch
(offline) and real-time (online) data shown are simulated; the feature
view registry itself is real. `FeatureViewDetailModal` (or page) shows:
metadata (entity column, source table, linked experiment name),
side-by-side batch-rows table vs. a single-entity real-time card with a
believable low-millisecond latency badge, and a "Materialize now" action
that refetches the real-time card with a fresh timestamp — hidden for
MRM per §0.2.

---

## 4. Local development — no Docker

Nothing here ever needed Docker. Prerequisite: Node 20 (no Python, no
Java, no AWS emulation needed on the frontend side at all).

### `scripts/dev.mjs` — implement fully (Node, ESM, no bash/PowerShell-
specific syntax, so it runs identically on Windows/macOS/Linux)

Don't just tell a developer to run `npm run dev` and hope the backend
happens to be up — the single most common local-dev failure mode across
two separate repos is starting the frontend before the backend, which
doesn't error clearly, it just produces a wall of CORS/network errors in
the browser console that look like a frontend bug. Catch that explicitly:

- Reads `VITE_API_BASE_URL` from `.env` (copying `.env.example` to `.env`
  first if it doesn't exist yet, same as the backend project's script).
- Polls `${VITE_API_BASE_URL}/health` with a short timeout (e.g. 10s,
  checking every 500ms). If it never responds:
  - Print a clear, specific error — not a generic timeout message:
    ```
    ❌ Can't reach the backend at http://localhost:8000/health

    Start the backend project first (separate repo):
      cd ../<backend-repo> && python scripts/dev.py

    Then re-run this script.
    ```
  - Exit non-zero. Do **not** start Vite anyway.
- Once the backend responds, spawn `vite` (via the same mechanism
  `npm run dev` would use) as the foreground process, so Ctrl+C in this
  terminal stops it normally.
- On success, print:
  ```
  ✅ Backend reachable at http://localhost:8000 — starting frontend

  Frontend:  http://localhost:3000
  ```
  then hand off to Vite's own startup output.

Wire this up so `npm run dev` invokes `node scripts/dev.mjs` (which
internally starts Vite) rather than calling `vite` directly — the
backend-readiness check should be the default path, not an opt-in extra
step a developer has to remember.

### Manual steps (what `dev.mjs` automates)

1. `npm install`
2. Copy `.env.example` to `.env` —
   `VITE_API_BASE_URL=http://localhost:8000`, `VITE_DEMO_MODE=true`.
3. **Start the backend project first** (its own `python scripts/dev.py`)
   so this frontend has something to call.
4. `npm run dev` — Vite dev server on `http://localhost:3000`, now with
   the backend-reachability check described above.

`package.json` scripts: `dev` (→ `node scripts/dev.mjs`), `build`
(`tsc && vite build`), `preview`, `type-check` (`tsc --noEmit`).

### Troubleshooting

- **CORS errors in the browser console**: the backend's
  `CORS_ALLOWED_ORIGINS` env var must include this frontend's actual
  origin (`http://localhost:3000` by default) — check the *backend*
  project's `.env`, not anything here.
- **`dev.mjs` times out even though the backend looks like it's
  running**: confirm `VITE_API_BASE_URL` in this project's `.env` matches
  the port the backend actually bound to (its own `dev.py` prints this on
  startup).

---

## 5. GitLab CI

```yaml
stages: [test, build]

test:
  stage: test
  image: node:20-alpine
  script:
    - npm ci
    - npm run type-check
    - npm run build

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

`Dockerfile` (CI-only, never used locally): multi-stage — `build` stage
runs `npm ci && npm run build`; final stage is `nginx:alpine` serving
`/dist` with SPA-fallback routing (all non-API, non-asset paths →
`index.html`), gzip, cache headers for hashed assets.

---

## 6. README

Quick start at the top: clone → `npm install` → (start the backend
project first!) → `npm run dev`. Explicitly state: **no Docker needed for
local development** — Docker only appears in GitLab CI to build the
deployment image. A short "how this relates to the backend project"
section (separate repo, integrate over `VITE_API_BASE_URL`, CORS is
configured on the backend side). Role-switching note: the demo
role-selector on the login page is cosmetic — the actual role always
comes from the backend's `DEV_USER_ROLE`, so to test as a different role
you change it in the *backend* project's `.env` and restart that process,
not anything here.

---

## 7. Output format

Produce every file in dependency order: types → api → hooks → layout →
shared components → page components → App.tsx/main.tsx → GitLab CI/
Dockerfile → README. No placeholders, no omitted files. Map every generic
component reference onto the real Truist component library per the note
in §0.

## 8. Verification checklist

- [ ] `npm run type-check` clean, `npm run build` succeeds
- [ ] With the backend project running, `npm run dev` loads the login
      page; demo-mode role selector works; landing page matches the
      selected role (Data Scientist → its dashboard, MRM → Governance,
      etc.)
- [ ] Every page reachable from the sidebar for every role loads without
      a console error (check all four roles — restart the *backend*
      process between role switches, per that project's README)
- [ ] Job submission wizard: all three Data Source tabs render, Feature
      Store tab is visibly disabled with a tooltip, submitting a job
      lands you on Jobs with the new job visible and polling
- [ ] Jobs page: the "View run" link on a submitted job actually opens
      that run in the Experiment comparison view, and its status
      visibly progresses over ~35s without a page refresh
- [ ] MRM cannot see any create/submit/register/materialize button
      anywhere it shouldn't (cross-check against the backend's actual
      403 boundary, don't just eyeball the UI)
