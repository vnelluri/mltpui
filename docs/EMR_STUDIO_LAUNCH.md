# EMR Studio launch flow — end to end

How a "Launch EMR Studio" click in the UI becomes an authenticated notebook
session, and where `EMR_STUDIO_URL` comes from. Companion to
[ARCHITECTURE.md](../ARCHITECTURE.md) §3.6/§4.1 and
[backend/iac-emr-studio/README.md](../backend/iac-emr-studio/README.md).

The core design: the backend **deep-links** into a single, platform-global
EMR Studio and never calls the EMR Studio API. There is no presigning for
EMR Studio — the URL is static and identical for every user and tenant;
per-user identity comes from the SSO sign-in behind it, not from the link.

## 1. Runtime flow (a user clicks "Launch EMR Studio")

```
Browser (NotebookPage)                Backend (FastAPI)                    AWS
──────────────────────                ─────────────────                    ───
POST /notebooks/launch ─────────────► notebooks.py router
  { sessionType: 'emr_studio',          │ require_role(TenantAdmin |
    tenantId, usecaseId? }              │              DataScientist)
                                        │ enforce_tenant_access()
                                        │ notebook_service.launch()
                                        │   └─ returns settings.EMR_STUDIO_URL
                                        │      (+ '#collab=usecase:<id>' if set)
                                        │ NotebookSession → DynamoDB
                                        │ audit_service.record('notebook.launch')
  ◄──────────────────────────────────── 201 { presignedUrl, urlExpiresAt, … }
window.open(presignedUrl) ──────────────────────────────────────────────► EMR Studio URL
                                                                          │ IAM Identity Center SSO
                                                                          │ (federated to Entra ID)
                                                                          │ session mapping check →
                                                                          │ user role + session policy
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
   requires `TenantAdmin` or `DataScientist`, enforces tenant access, calls
   the service, persists a `NotebookSession` row in DynamoDB (1-hour
   `urlExpiresAt`), and writes a `notebook.launch` audit event. Session URLs
   are returned once and never re-read from storage — past sessions in the UI
   are metadata only ("Relaunch to open").

3. **Service** — `backend/app/services/notebook_service.py`
   `launch_emr_studio()` simply returns `settings.EMR_STUDIO_URL`. No AWS
   call, no presigning (the `presignedUrl` field name is only meaningful for
   the SageMaker path, which really does call
   `sagemaker:CreatePresignedDomainUrl`). If `usecaseId` was passed, the
   service appends `#collab=usecase:<id>` — a URL *fragment*, so it can never
   invalidate a signature — which the Studio-side bootstrap uses to land
   collaborators in a shared workspace. With `EMR_MOCK_MODE=true` (local
   dev), a fake `https://mock-emr.local/session/<uuid>` is returned instead.

4. **Sign-in** — the new tab hits the Studio access URL. IAM Identity Center
   (Entra-federated, groups SCIM-synced) authenticates the actual user. EMR
   Studio then looks for a **session mapping** for the user or one of their
   groups; **no mapping → no session**. A matched mapping starts a federated
   session that assumes the shared user role, further restricted by the
   mapped session policy (`basic` or `intermediate`) — effective permissions
   are the intersection of the two.

5. **Attach** — inside the Studio the user attaches their Workspace to an
   EMR Serverless application (created per tenant by `tmt-dataplane`; the
   Studio provisions no compute of its own). `basic` can browse and attach;
   `intermediate` can additionally start/stop applications and
   start/cancel job runs. Notebook files persist to the module's
   `default_s3_location` prefix in the control-plane artifacts bucket.

Known limitation (ARCHITECTURE.md §3.6): the Studio is platform-global while
compute/data are per-tenant, so session policies cannot scope by tenant —
treat notebook attach as platform-wide within a user's tier until per-tenant
Studios ship.

## 2. Where `EMR_STUDIO_URL` comes from

The value originates in Terraform and reaches the app via SSM:

```
backend/iac-emr-studio (module)          Pipeline root                Backend task
───────────────────────────────          ─────────────                ────────────
aws_emr_studio.this.url                  aws_ssm_parameter            ECS task definition
  └─ output "url" ─────────────────────►  /ml-platform/emr/           injects SSM param as
     (Studio access URL)                  studio-url ────────────────► EMR_STUDIO_URL env var
                                                                        └─ app/config.py
                                                                           settings.EMR_STUDIO_URL
```

1. **Module output** — `backend/iac-emr-studio/outputs.tf` exposes `url`,
   the `aws_emr_studio` resource's access URL (the module is provider-less;
   instantiate it from your pipeline root — the **backend** pipeline is the
   one that applies it, with a dataplane-account provider alias if you run
   the two-account split).

2. **Pipeline root writes SSM** — per the module README, the root maps the
   output into the control-plane parameter the backend expects:

   ```hcl
   module "emr_studio" {
     source = "git::https://<host>/tmt.git//backend/iac-emr-studio?ref=main"

     name_prefix         = "ml-platform"
     vpc_id              = var.vpc_id
     subnet_ids          = var.private_subnet_ids
     default_s3_location = "s3://ml-platform-artifacts-prod/emr-studio-workspaces"

     session_mappings = {
       "myapp-platform-admin"       = "intermediate"
       "myapp-team-a-datascientist" = "basic"
     }
   }

   resource "aws_ssm_parameter" "emr_studio_url" {
     name  = "/ml-platform/emr/studio-url"
     type  = "String"
     value = module.emr_studio.url
   }
   ```

3. **ECS injects it** — `backend/iac/main.tf` lists
   `EMR_STUDIO_URL = "${local.ssm_arn}/emr/studio-url"` among the SSM-backed
   container secrets; ECS resolves the parameter at task start and injects it
   as the `EMR_STUDIO_URL` environment variable.

4. **App reads it** — `backend/app/config.py` declares
   `EMR_STUDIO_URL: Optional[str]`; `notebook_service.launch_emr_studio()`
   returns it, or raises a clear error if unset ("Provision an EMR Studio in
   SSO auth mode … the platform only deep-links into it").

Local dev never needs the real URL: `backend/.env.example` leaves
`EMR_STUDIO_URL=` empty and `EMR_MOCK_MODE` supplies mock session URLs.

## 3. Which account does what (two-account split)

A common point of confusion: **the Studio URL is never configured in
Identity Center** — AWS generates the access URL when the `aws_emr_studio`
resource is created (the module's `url` output), and Identity Center never
needs to be told about it. Each piece lives here:

| Piece | Account | Notes |
|---|---|---|
| IAM Identity Center instance (Entra federation, SCIM group sync) | **Org management account** (or delegated admin) — *neither* control-plane nor dataplane | Organization-level service, enabled once; this is where the Entra IdP federation and `myapp-*` group sync are configured |
| EMR Studio resource + session mappings | **Dataplane account** | Created by `backend/iac-emr-studio` (applied by the backend pipeline via a dataplane provider alias), next to the EMR Serverless applications it attaches to. Works from a member account as long as it belongs to the org where Identity Center is enabled; session mappings reference Identity Center identities by name but are created here |
| SSM parameter `/ml-platform/emr/studio-url` | **Control-plane account** | The only Studio-related thing in the control plane: the URL string the backend reads to deep-link |
| Access-portal tile (optional) | Org management account | Purely cosmetic: a custom app/bookmark in the Identity Center access portal pointing at the dataplane Studio URL. The platform doesn't rely on it — users arrive via the app's launch button |

In a **single-account deployment** the first three collapse into one account
(Identity Center still requires an AWS Organizations org, even a
one-account org).

## 4. Prerequisites checklist

Everything the flow above assumes is already in place:

- **IAM Identity Center enabled** at the organization level (management or
  delegated-admin account — see §3), Entra ID federated as the external IdP,
  and the platform's security groups (`myapp-{tenant}-{role}`,
  `myapp-platform-admin`, …) SCIM-synced. This is org/account-level
  configuration the Terraform module cannot create.
- **`session_mappings` populated** — keys must exactly match Identity Center
  identity names (group names with the default
  `session_identity_type = "GROUP"`). Empty map = nobody can start a session.
- **`backend/iac-emr-studio` applied** by the backend pipeline — into the
  dataplane account when running the two-account split (next to the EMR
  Serverless applications it attaches to), or the single account otherwise.
- **SSM parameter `/ml-platform/emr/studio-url` written** from the module's
  `url` output, and the backend ECS service (re)deployed so the task picks
  it up.
- **At least one tenant provisioned** via the `tmt-dataplane` reconcile
  pipeline — otherwise there is no EMR Serverless application to attach a
  Workspace to, and the Studio is a lobby with no rooms.
