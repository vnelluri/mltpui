# EMR Studio launch flow — end to end

How a "Launch EMR Studio" click in the UI becomes an authenticated notebook
session. Companion to [ARCHITECTURE.md](../ARCHITECTURE.md) §3.6/§4.1 and the
EMR Studio module README (in the companion `tmt-dataplane` repo,
`modules/emr-studio`). For the full IAM-mode design + trade-offs see
[EMR_STUDIO_IAM_MODE.md](EMR_STUDIO_IAM_MODE.md).

> **Two auth modes.** The platform **defaults to IAM mode** (no Identity
> Center): at launch the backend assumes a per-tier IAM role and calls
> `CreateStudioPresignedUrl`. **SSO mode** (IAM Identity Center) is the opt-in
> alternative (`EMR_AUTH_MODE=SSO` + module `auth_mode = "SSO"`): the backend
> deep-links a static URL and Identity Center authenticates the user. This doc
> leads with IAM; SSO differences are called out inline.

> **Where the notebook actually runs: the dataplane account, always.** The EMR
> Studio, its Workspaces, and the EMR Serverless compute all live in the
> dataplane account. What differs by mode is how the user gets *in*:
> - **IAM (default):** at launch the backend makes a cross-account call — assume
>   a dataplane tier role, `CreateStudioPresignedUrl` — and returns a short-lived
>   URL the user opens straight into the dataplane Studio.
> - **SSO:** the backend hands back a static URL it read from SSM; Identity
>   Center authenticates the user when they open it (no API call at launch).
>
> Either way, once the user is in, the notebook session and its attach to EMR
> Serverless are same-account inside the dataplane. Training-**job** submission
> is a separate cross-account path (backend → `StartJobRun`, no Studio
> involved) — see §3.

## 1. Runtime flow (a user clicks "Launch EMR Studio")

```
Browser (NotebookPage)        Backend (FastAPI)                      Dataplane account
──────────────────────        ─────────────────                      ─────────────────
POST /notebooks/launch ─────► notebooks.py router
  { sessionType:'emr_studio',  │ require_role(TenantAdmin | DataScientist)
    tenantId, usecaseId? }     │ enforce_tenant_access()
                               │ notebook_service.launch(role)
                               │  IAM: tier = basic | intermediate (from role)
                               │       sts:AssumeRole tier-role
                               │        RoleSessionName=<stable user id>, tags ─► …-emr-studio-{tier}
                               │       emr.CreateStudioPresignedUrl(StudioId) ──► EMR Studio (IAM)
                               │  SSO: return settings.EMR_STUDIO_URL (static)
                               │ NotebookSession → DynamoDB
                               │ audit_service.record('notebook.launch')
  ◄──────────────────────────── 201 { presignedUrl, urlExpiresAt }
window.open(presignedUrl) ───────────────────────────────────────────────► Workspace (Jupyter)
                                                                            │ attach to a tenant's
                                                                            ▼ EMR Serverless app
                                                                          Compute (from tmt-dataplane)
```

Step by step:

1. **Frontend** — `frontend/src/pages/workspace/NotebookPage.tsx` calls
   `POST /notebooks/launch` with `{ sessionType: 'emr_studio', tenantId }`,
   then opens the returned URL in a new tab
   (`window.open(session.presignedUrl, '_blank', 'noopener,noreferrer')`).
   Launching requires a tenant-scoped role; roles without a tenant see an
   explanation instead of the button.

2. **Router** — `backend/app/routers/notebooks.py` (`POST /notebooks/launch`):
   requires `TenantAdmin` or `DataScientist`, enforces tenant access, calls the
   service (passing the user's active role), persists a `NotebookSession` row,
   and writes a `notebook.launch` audit event. Session URLs are returned once
   and never re-read from storage — past sessions in the UI are metadata only
   ("Relaunch to open"). `urlExpiresAt` is **~5 min in IAM mode** (the presigned
   redemption window) and 1 hour in SSO mode.

3. **Service** — `backend/app/services/notebook_service.py`
   `launch_emr_studio(tenant_id, user_id, role)` branches on `EMR_AUTH_MODE`:
   - **IAM (default):** map role → tier (`DataScientist → basic`;
     `TenantAdmin`/`PlatformAdmin → intermediate`), `sts:AssumeRole` that tier
     role with a **stable `RoleSessionName` = the user's id** (plus `user` /
     `tenantId` session tags), then `emr.create_studio_presigned_url(StudioId=…)`
     and return `AuthorizedUrl`. Mirrors the SageMaker presign path
     (`launch_sagemaker_studio`, `sagemaker:CreatePresignedDomainUrl`).
   - **SSO:** return `settings.EMR_STUDIO_URL` (static), or raise if unset. No
     AWS call.
   - Either mode: if `usecaseId` was passed, append `#collab=usecase:<id>` — a
     URL *fragment*, so it can never invalidate a presigned signature — which
     the Studio-side bootstrap uses to land collaborators in a shared workspace.
     With `EMR_MOCK_MODE=true` (local dev) a fake
     `https://mock-emr.local/session/<uuid>` is returned before any of this.

4. **Sign-in** — the new tab hits the Studio:
   - **IAM:** the presigned URL logs the user in as the **assumed tier-role
     session** (`aws:userId` = `<tier-role-id>:<user-id>`). Per-user Workspace
     ownership holds because EMR Studio tags each Workspace `creatorUserId =
     ${aws:userId}` (see EMR_STUDIO_IAM_MODE.md). The URL must be opened within
     the presigned window (~5 min).
   - **SSO:** the URL redirects through IAM Identity Center (Entra-federated);
     EMR Studio looks for a **session mapping** for the user/group (**no mapping
     → no session**) and starts a federated session under the shared user role,
     narrowed by the mapped session policy.

5. **Attach** — inside the Studio the user attaches their Workspace to an EMR
   Serverless application (created per tenant by `tmt-dataplane`; the Studio
   provisions no compute of its own). `basic` can browse and attach;
   `intermediate` can additionally start/stop applications and start/cancel job
   runs. Notebook files persist to the module's `default_s3_location` prefix in
   the dataplane artifacts bucket.

Known limitation (ARCHITECTURE.md §3.6): the Studio is platform-global while
compute/data are per-tenant, so a user's tier is platform-wide — treat notebook
attach as platform-wide within a tier until per-tenant Studios ship.

## 2. How the backend reaches the Studio (config)

### IAM mode (default)

The backend needs the Studio id and the two tier role ARNs, and permission to
assume them. All come from the `tmt-dataplane` root outputs (wired in like
`runtime_role_arn` already is):

| Backend setting | Value (from `tmt-dataplane` outputs) |
|---|---|
| `EMR_AUTH_MODE` | `IAM` |
| `EMR_STUDIO_ID` | `emr_studio_id` (the module's `studio_id`) |
| `EMR_STUDIO_BASIC_ROLE_ARN` | `emr_studio_tier_role_arns["basic"]` |
| `EMR_STUDIO_INTERMEDIATE_ROLE_ARN` | `emr_studio_tier_role_arns["intermediate"]` |
| `backend/iac` `emr_studio_tier_role_arns` | both ARNs — adds the task role's `sts:AssumeRole` grant |

There is **no `EMR_STUDIO_URL` and no SSM URL parameter** in IAM mode — the URL
is minted per launch.

### SSO mode (alternative)

The static Studio URL reaches the app via SSM:

```
tmt-dataplane emr-studio module        SSM (control plane)      Backend task
──────────────────────────────         ───────────────────      ────────────
aws_emr_studio.this.url ─────────────► /ml-platform/emr/         ECS injects as
  (module `url` output)                 studio-url ────────────► EMR_STUDIO_URL env var
```

The operator writes the module's `url` output to `/ml-platform/emr/studio-url`;
`backend/iac/main.tf` injects that SSM param as `EMR_STUDIO_URL`;
`notebook_service.launch_emr_studio()` returns it. `backend/app/config.py`
declares `EMR_STUDIO_URL: Optional[str]` and raises a clear error if it's unset
while `EMR_AUTH_MODE=SSO`.

Local dev needs neither: `backend/.env.example` leaves both blank and
`EMR_MOCK_MODE` supplies mock session URLs.

## 3. Compute access: attach vs. submit

"EMR Studio → EMR Serverless" and "control plane → dataplane" are **two
different access paths**. The design keeps them apart on purpose, and conflating
them is the usual source of confusion.

The placement fact that makes this work: the **Studio is deployed into the
dataplane account** (§4), applied by `tmt-dataplane` (from its `account-baseline`
layer), *next to* the per-tenant EMR Serverless applications. That is what makes
the notebook attach same-account.

### Path 1 — notebook attach (Studio ↔ EMR Serverless)

Happens **entirely inside the dataplane account, in the user's browser
session**; the backend is not involved after launch.

- **Identity** — the Studio session is either the presigned **tier-role**
  session (IAM mode) or the shared **user role** narrowed by a session policy
  (SSO mode). Either way the role and the EMR Serverless apps live in the
  dataplane account → a **same-account** attach, no cross-account STS.
- **Attach** — the user picks an EMR Serverless application as the Workspace
  engine; the browse is `emr-serverless:ListApplications`/`GetApplication`. Apps
  offered are the per-tenant ones from `tmt-dataplane`.
- **Network** — the two-SG model: Workspace SG → **Engine SG on port 18888
  only** (Jupyter Enterprise Gateway). That 18888 hop is the actual runtime wire
  between notebook and compute.
- **Storage** — notebook `.ipynb` files write to `default_s3_location`, a prefix
  in the **dataplane** artifacts bucket (SSE-KMS; the Studio roles hold KMS use
  on its CMK).

### Path 2 — job submission (backend → EMR Serverless)

The *other* way EMR Serverless is used — training jobs, driven by the backend,
**no Studio involved** — and the one that crosses accounts at request time. The
control-plane backend task role does **`sts:AssumeRole` + `TagSession`** on the
dataplane **runtime role** with a `tenantId` session tag (**ABAC**), then calls
`emr-serverless:StartJobRun`, constrained by the `platform=<name_prefix>`
resource tag and `iam:PassRole` limited to the tenant execution-role pattern
(ARCHITECTURE.md §4.2).

### Why the difference matters

|  | Path 1: notebook attach | Path 2: job submit |
|---|---|---|
| Driven by | user's browser (Studio) | backend (FastAPI) |
| Identity | Studio tier-role / user-role session | control-plane task role → assumed dataplane runtime role |
| Cross-account? | **No** — Studio co-located with apps | **Yes** — STS AssumeRole + `tenantId` ABAC tag |
| Tenant isolation | **None** — any tier user can attach to any tenant's app | **Per-tenant** — ABAC tag + execution role + KMS |

This asymmetry is the documented known limitation (ARCHITECTURE.md §3.6): job
*submission* is tenant-isolated by ABAC, but notebook *attach* is not — a user
in one tenant can attach a Workspace to another tenant's app. Per-tenant Studios
are the deferred fix.

> Note on the launch call itself: in **IAM mode** minting the URL *is* a
> cross-account control→dataplane call (assume tier role + presign), unlike SSO
> where launch just returns a static string. Either way it only mints access —
> the notebook session and compute still run entirely in the dataplane.

### Two dependencies this repo does not enforce

- **Interactive endpoint on the EMR Serverless apps.** A Workspace can only
  attach to an application with its interactive endpoint enabled
  (`interactiveConfiguration` / Livy). The `tmt-dataplane` tenant module creates
  the apps — that flag must be set there, or attach silently offers nothing.
- **Same VPC/subnet reachability.** The Studio Engine SG and each EMR Serverless
  application's network config must sit in subnets that can reach each other on
  18888. Both are in the dataplane account, so line up the `subnet_ids` passed
  to the emr-studio module with the apps' network config.

## 4. Which account does what

| Piece | Account | Notes |
|---|---|---|
| EMR Studio + tier roles + SGs (IAM mode) | **Dataplane** | Created by `tmt-dataplane/modules/emr-studio`, applied by `tmt-dataplane` (account-baseline), next to the EMR Serverless apps. In SSO mode this also includes the shared user role + session policies + session mappings. |
| Backend Studio config | **Control plane** | IAM mode: `EMR_STUDIO_ID` + tier role ARNs (backend assumes them to presign). SSO mode: the SSM param `/ml-platform/emr/studio-url` the backend reads to deep-link. |
| Artifacts bucket (Workspace storage) | **Dataplane** | Created by `account-baseline`; the backend reaches it cross-account. |
| IAM Identity Center (Entra federation, SCIM) | **Org management / delegated admin** | **SSO mode only.** Org-level service; where Entra federation and `myapp-*` group sync live. Not used in IAM mode. |

In a **single-account deployment** the control-plane and dataplane pieces
collapse into one account.

## 5. Prerequisites checklist

### IAM mode (default)

- **`tmt-dataplane/modules/emr-studio` applied** with `auth_mode = "IAM"` and
  `backend_principal_arns = [<backend task role ARN>]` (the tier roles trust it),
  in the dataplane account.
- **Backend configured** — `EMR_AUTH_MODE=IAM`, `EMR_STUDIO_ID`, both tier role
  ARNs, and `backend/iac` `emr_studio_tier_role_arns` (for the `sts:AssumeRole`
  grant). The prod boot-guard refuses to start if `EMR_AUTH_MODE=IAM` and any of
  these are missing.
- **At least one tenant provisioned** via the `tmt-dataplane` reconcile pipeline
  (with its EMR Serverless app's **interactive endpoint enabled**) — otherwise
  there is nothing to attach a Workspace to.

### SSO mode (alternative)

- **IAM Identity Center enabled** org-wide, Entra federated, `myapp-*` groups
  SCIM-synced (org/account-level config the module cannot create).
- **`auth_mode = "SSO"` and `session_mappings` populated** — keys must match
  Identity Center identity names exactly. Empty map = nobody can start a session.
- **SSM `/ml-platform/emr/studio-url` written** from the module's `url` output,
  and `EMR_AUTH_MODE=SSO` on the backend.
- Same tenant/interactive-endpoint prerequisite as above.
