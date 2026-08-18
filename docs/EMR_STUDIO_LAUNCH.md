# EMR Studio launch flow — end to end

How a "Launch EMR Studio" click in the UI becomes an authenticated notebook
session. Companion to [ARCHITECTURE.md](../ARCHITECTURE.md) §3.6/§4.1 and the
EMR Studio module README (in the companion `tmt-dataplane` repo,
`modules/emr-studio`). For the full IAM-mode design + trade-offs see
[EMR_STUDIO_IAM_MODE.md](EMR_STUDIO_IAM_MODE.md).

> **Two auth modes, one launch path.** The platform **defaults to IAM mode**
> (no Identity Center); **SSO mode** (IAM Identity Center) is the opt-in
> alternative (`EMR_AUTH_MODE=SSO` + module `auth_mode = "SSO"`). The mode is a
> property of how the *Studio* authenticates users, **not a backend code
> branch**: in both modes the backend returns the Studio's static **access URL**
> (`EMR_STUDIO_URL`, read from SSM) and AWS's hosted sign-in flow authenticates
> the user. The backend never calls the EMR Studio API —
> `CreateStudioPresignedUrl` is not in the boto3 SDK; see
> [EMR_STUDIO_IAM_MODE.md](EMR_STUDIO_IAM_MODE.md).

> **Where the notebook actually runs: the dataplane account, always.** The EMR
> Studio, its Workspaces, and the EMR Serverless compute all live in the
> dataplane account. What differs by mode is how the user gets *in*:
> - **IAM (default):** the access URL redirects to IAM sign-in — or, with IAM
>   federation to Entra, to the IdP — and the user lands in the Studio as their
>   own federated tier-role session.
> - **SSO:** the access URL redirects through IAM Identity Center, which
>   supplies the user's Entra identity.
>
> Either way, once the user is in, the notebook session and its attach to EMR
> Serverless are same-account inside the dataplane. Training-**job** submission
> is a separate cross-account path (backend → `StartJobRun`, no Studio
> involved) — see §3.

## 1. Runtime flow (a user clicks "Launch EMR Studio")

```
Browser (NotebookPage)        Backend (FastAPI)                Dataplane account
──────────────────────        ─────────────────                ─────────────────
POST /notebooks/launch ─────► notebooks.py router
  { sessionType:'emr_studio',  │ require_role(TenantAdmin | DataScientist)
    tenantId, usecaseId? }     │ enforce_tenant_access()
                               │ notebook_service.launch()
                               │   → settings.EMR_STUDIO_URL (no AWS call)
                               │ NotebookSession → DynamoDB
                               │ audit_service.record('notebook.launch')
  ◄──────────────────────────── 201 { presignedUrl = access URL, urlExpiresAt }
window.open(access URL) ─────────────────────────────────────► Studio access URL
                                                                │ hosted sign-in:
                                                                │  IAM / IAM-federation (IAM mode)
                                                                │  Identity Center (SSO mode)
                                                                │ then CreateStudioPresignedUrl
                                                                │ (the user's own permission)
                                                                ▼
                                                              Workspace (Jupyter)
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
   ("Relaunch to open"). The `presignedUrl` field name is historical: it carries
   the static access URL, which does not expire — `urlExpiresAt` is a nominal
   1-hour stamp; sign-in happens when the user opens the URL.

3. **Service** — `backend/app/services/notebook_service.py`
   `launch_emr_studio()` returns `settings.EMR_STUDIO_URL` (or raises with a
   pointer to this setup if unset). It does **not** branch on `EMR_AUTH_MODE`
   and makes **no AWS call** — the auth mode is a property of the Studio, not
   of this code path.
   - Either mode: if `usecaseId` was passed, `launch()` appends
     `#collab=usecase:<id>` — a URL *fragment*, so it can never invalidate a
     presigned signature. The fragment is a **best-effort breadcrumb only**:
     nothing AWS-side reads it, and it does not survive the SAML sign-in hop
     (the HTTP-POST binding drops fragments; it arrives only for users whose
     Studio session is already active). **Collaborative mode works by
     convention instead**: collaborators create/join the Workspace named
     `usecase-<id>` and enable EMR Studio's built-in collaboration; the
     platform records `usecaseId` on the session as governance metadata and
     the UI surfaces the convention. With `EMR_MOCK_MODE=true` (local dev) a
     fake `https://mock-emr.local/session/<uuid>` is returned before any of
     this.

4. **Sign-in** — the new tab hits the Studio's access URL and AWS's hosted flow
   authenticates the user, then calls `CreateStudioPresignedUrl` **under the
   user's own identity** (their grant on the Studio ARN — not anything the
   backend does):
   - **IAM:** the access URL redirects to IAM sign-in — or, with IAM federation
     to Entra, to a SAML sign-in that lands the user in a per-tier role via
     `sts:AssumeRoleWithSAML`. Per-user Workspace ownership holds because EMR
     Studio tags each Workspace `creatorUserId = ${aws:userId}` (see
     EMR_STUDIO_IAM_MODE.md).
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

**Both modes, one wire** — the static Studio access URL reaches the app via
SSM:

```
tmt-dataplane emr-studio module        SSM (control plane)      Backend task
──────────────────────────────         ───────────────────      ────────────
aws_emr_studio.this.url ─────────────► /ml-platform/emr/         ECS injects as
  (module `url` output; root            studio-url ────────────► EMR_STUDIO_URL env var
   output `emr_studio_url`)
```

The operator writes the module's `url` output (root output `emr_studio_url`)
to `/ml-platform/emr/studio-url`; `backend/iac/main.tf` injects that SSM param
as `EMR_STUDIO_URL`; `notebook_service.launch_emr_studio()` returns it.
`backend/app/config.py` declares `EMR_STUDIO_URL: Optional[str]`, and the prod
boot-guard **refuses to start** if it is unset (both modes) — a missing URL
fails at deploy time, not at click time.

`EMR_AUTH_MODE` (`IAM` default / `SSO`) documents which way the Studio was
provisioned; the launch path does not branch on it. The old IAM-mode settings
(`EMR_STUDIO_ID`, `EMR_STUDIO_BASIC/INTERMEDIATE_ROLE_ARN`) and the
`backend/iac` `emr_studio_tier_role_arns` variable are **gone** — the backend
no longer presigns, so it needs neither the Studio id nor any role to assume.

Local dev needs none of this: `backend/.env.example` leaves `EMR_STUDIO_URL`
blank and `EMR_MOCK_MODE` supplies mock session URLs.

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

- **Identity** — the Studio session is the user's own federated **tier-role**
  session (IAM mode — `sts:AssumeRoleWithSAML` via the Studio's SAML provider)
  or the shared **user role** narrowed by a session policy (SSO mode). Either
  way the role and the EMR Serverless apps live in the dataplane account → a
  **same-account** attach, no cross-account STS.
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
| Identity | user's own federated Studio session (tier role / user role) | control-plane task role → assumed dataplane runtime role |
| Cross-account? | **No** — Studio co-located with apps | **Yes** — STS AssumeRole + `tenantId` ABAC tag |
| Tenant isolation | **None** — any tier user can attach to any tenant's app | **Per-tenant** — ABAC tag + execution role + KMS |

This asymmetry is the documented known limitation (ARCHITECTURE.md §3.6): job
*submission* is tenant-isolated by ABAC, but notebook *attach* is not — a user
in one tenant can attach a Workspace to another tenant's app. Per-tenant Studios
are the deferred fix.

> Note on the launch call itself: in **neither mode** does launch touch AWS —
> the backend returns the static access URL and sign-in happens later, in the
> user's browser, under the user's own identity. Launch only points at access —
> the notebook session and compute run entirely in the dataplane.

### Two dependencies to keep in mind

- **Interactive endpoint on the EMR Serverless apps.** A Workspace can only
  attach to an application with its interactive endpoint enabled
  (`interactiveConfiguration` / Livy). Tenant provisioning
  (`tenant_provisioning_service.py`) creates the apps with
  `studioEnabled`/`livyEndpointEnabled` on — apps created out-of-band must
  set the flag too, or attach silently offers nothing.
- **Same VPC/subnet reachability.** The Studio Engine SG and each EMR Serverless
  application's network config must sit in subnets that can reach each other on
  18888. Both are in the dataplane account, so line up the `subnet_ids` passed
  to the emr-studio module with the apps' network config.

## 4. Which account does what

| Piece | Account | Notes |
|---|---|---|
| EMR Studio + tier roles + SGs (IAM mode) | **Dataplane** | Created by `tmt-dataplane/modules/emr-studio`, applied by `tmt-dataplane` (account-baseline), next to the EMR Serverless apps. The tier roles trust the SAML provider for `sts:AssumeRoleWithSAML`. In SSO mode this instead includes the shared user role + session policies + session mappings. |
| SAML IAM identity provider (Entra federation) | **Dataplane** | **IAM mode only.** Created out-of-band by an IAM admin and passed to the module by ARN (`saml_provider_arn`); the module never calls `iam:CreateSAMLProvider`. Entra side: [EMR_STUDIO_FEDERATION_REQUEST.md](EMR_STUDIO_FEDERATION_REQUEST.md). |
| Backend Studio config | **Control plane** | **Both modes:** the SSM param `/ml-platform/emr/studio-url` the backend reads to deep-link (`EMR_STUDIO_URL`), plus `EMR_AUTH_MODE` (documents the Studio's mode; no code branch). |
| Artifacts bucket (Workspace storage) | **Dataplane** | Created by `account-baseline`; the backend reaches it cross-account. |
| IAM Identity Center (Entra federation, SCIM) | **Org management / delegated admin** | **SSO mode only.** Org-level service; where Entra federation and `myapp-*` group sync live. Not used in IAM mode. |

In a **single-account deployment** the control-plane and dataplane pieces
collapse into one account.

## 5. Prerequisites checklist

### IAM mode (default)

- **SAML provider created** by an IAM admin in the dataplane account (Entra
  federation metadata) — referenced by ARN, never created by the stack.
- **`tmt-dataplane/modules/emr-studio` applied** with `auth_mode = "IAM"` and
  `saml_provider_arn = <that ARN>` (the tier roles trust it for
  `sts:AssumeRoleWithSAML`), in the dataplane account.
- **Entra-side SAML app configured** (enterprise app, claims, group→role
  mapping to the tier roles) per
  [EMR_STUDIO_FEDERATION_REQUEST.md](EMR_STUDIO_FEDERATION_REQUEST.md). This is
  what "assigns" users: the tier roles carry
  `elasticmapreduce:CreateStudioPresignedUrl` on the Studio ARN, which the
  hosted sign-in flow needs to complete.
- **SSM `/ml-platform/emr/studio-url` written** from the module's `url` output
  (root `emr_studio_url`), and `EMR_AUTH_MODE=IAM` on the backend. The prod
  boot-guard refuses to start if `EMR_STUDIO_URL` is unset (both modes).
- **At least one tenant provisioned** (`POST /tenants` — the backend creates
  its EMR Serverless app directly, **interactive endpoint enabled**) —
  otherwise there is nothing to attach a Workspace to.

### SSO mode (alternative)

> Full ordered checklist with owners — including the IdC admin hand-off,
> Snowflake OBO track, and notebook-secret mitigations — in
> [SSO_MODE_RUNBOOK.md](SSO_MODE_RUNBOOK.md).

- **IAM Identity Center enabled** org-wide, Entra federated, `myapp-*` groups
  SCIM-synced (org/account-level config the module cannot create).
- **`auth_mode = "SSO"` and `session_mappings` populated** — keys must match
  Identity Center identity names exactly. Empty map = nobody can start a session.
- **SSM `/ml-platform/emr/studio-url` written** from the module's `url` output
  (root `emr_studio_url`), and `EMR_AUTH_MODE=SSO` on the backend.
- Same tenant/interactive-endpoint prerequisite as above.
