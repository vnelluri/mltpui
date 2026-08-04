# EMR Studio — IAM authentication mode (no Identity Center)

An alternative to the SSO/Identity Center design in
[EMR_STUDIO_LAUNCH.md](EMR_STUDIO_LAUNCH.md) and
[IDENTITY_CENTER_ADMIN_REQUEST.md](IDENTITY_CENTER_ADMIN_REQUEST.md). IAM mode
removes IAM Identity Center from the notebook path entirely, trading a
cross-org/cross-team coordination problem for self-contained backend code.

## Why

Creating an EMR Studio in **SSO auth mode** makes `CreateStudio` register the
Studio as a managed application in IAM Identity Center — it calls
`sso:CreateApplication` / `sso:CreateManagedApplicationInstance`. Our dataplane
CI/CD role's permissions boundary (`CSEStandardPermissionsBoundary`) denies
those, so the SSO pipeline fails. IAM mode's `CreateStudio` makes **no `sso:`
calls**, so it doesn't hit that wall — and it needs no Entra↔Identity Center
federation, no SCIM group sync, no session mappings, and no region-instance
coupling.

The cost: the backend must call the EMR Studio API at launch time (it made none
before), and tiering moves from Identity Center session mappings into backend
code. Both are small and fully under our control.

## How it works

```
Browser            Backend (control plane)                 Dataplane account
───────            ───────────────────────                 ─────────────────
POST /notebooks/launch ─► notebook_service.launch(role)
                          │ tier = basic | intermediate  (from user's role)
                          │ sts:AssumeRole tier-role
                          │   RoleSessionName = <stable user id>
                          │   Tags: user, tenantId ──────► …-emr-studio-{tier} role
                          │ emr.CreateStudioPresignedUrl(StudioId) ─► EMR Studio (IAM)
◄── 201 { presignedUrl } ─┘   AuthorizedUrl
window.open(AuthorizedUrl) ───────────────────────────────► Workspace (Jupyter)
```

Mirrors the existing SageMaker presign path (`notebook_service.launch_sagemaker_studio`,
`sagemaker:CreatePresignedDomainUrl`). The `NotebookSession` model already
carries `urlExpiresAt` for short-lived URLs, and the `#collab=usecase:<id>`
fragment still works (a fragment can't invalidate a presigned URL).

## Per-user identity (verified against AWS docs)

This is the crux — IAM mode **does** give per-user Workspace ownership, via a
documented mechanism:

- EMR Studio tags every Workspace with **`creatorUserId` = `${aws:userId}`**
  ([Set ownership for Workspace collaboration](https://docs.aws.amazon.com/emr/latest/ManagementGuide/emr-studio-user-permissions.html)).
- For an assumed-role session, `aws:userId` = `<role-unique-id>:<RoleSessionName>`.
  So two people assuming the **same** tier role get **different** `aws:userId`
  values (different session names) → different `creatorUserId` → distinct
  ownership. The tier roles scope the collaboration-management actions with
  `creatorUserId = ${aws:userId}`, so a user can only manage the Workspaces
  they created.

**Hard requirement this imposes:** the backend must assume the tier role with a
**stable, per-user `RoleSessionName`** (the Cognito `sub`/user id) — never a
random value — or a user would get a new `creatorUserId` each login and lose
ownership of their prior Workspaces. `notebook_service` uses the user id
(sanitized to the STS charset, ≤64 chars).

### What is weaker than SSO
Workspace **visibility** is shared — *"By default, a Workspace is shared and can
be seen by all Studio users"* — but that is true in SSO mode too, so it is not a
regression. What IAM mode gives: per-user **ownership**, **collaboration
control**, and **attribution**; what it doesn't add: per-user visibility
isolation (neither mode does without extra tag controls).

### Attribution for MRM/governance
- "Who launched a session" already lives in the app's own audit log
  (`notebook.launch` with `userId`) — mode-independent, the governance-grade
  record.
- In-Studio AWS API calls are attributed via `RoleSessionName` + the `user` /
  `tenantId` session tags in CloudTrail.
- The one thing SSO does natively that IAM mode approximates: a
  cryptographically distinct Studio identity per person. **Confirm this level of
  attribution satisfies MRM before adopting.**

## Terraform (`tmt-dataplane/modules/emr-studio`)

`auth_mode = "IAM"` (now the module default — set `"SSO"` for the Identity
Center path):

- **Creates** the Studio with `auth_mode = "IAM"` (no `user_role`), the two
  security groups, the service role, and **two assumable tier roles**
  (`…-emr-studio-basic`, `…-emr-studio-intermediate`) trusted by
  `backend_principal_arns` for `sts:AssumeRole`/`sts:TagSession`. Each tier role
  carries: `CreateStudioPresignedUrl`, Workspace lifecycle, creator-scoped
  collaboration, EMR Serverless browse/attach (intermediate adds application
  lifecycle), Workspace-bucket S3, and `iam:PassRole` for the service role
  (intermediate also for the job runtime role).
- **Skips** the SSO-only `user_role`, session policies, and session mappings.
- **Outputs** `tier_role_arns` (basic/intermediate → ARN) and `auth_mode`.

```hcl
module "emr_studio" {
  source                 = "./modules/emr-studio"
  name_prefix            = "ml-platform"
  vpc_id                 = var.vpc_id
  subnet_ids             = var.private_subnet_ids
  default_s3_location    = "s3://ml-platform-artifacts-prod/emr-studio-workspaces"
  auth_mode              = "IAM"
  backend_principal_arns = [var.backend_task_role_arn]
  emr_serverless_runtime_role_arn_pattern = var.tenant_execution_role_arn_pattern
}
```

`backend/iac` gets the tier-role ARNs via `emr_studio_tier_role_arns`, which adds
an `sts:AssumeRole`/`TagSession` grant on them to the task role.

## Backend config

| Setting | Value |
|---|---|
| `EMR_AUTH_MODE` | `IAM` |
| `EMR_STUDIO_ID` | the IAM-mode Studio id (module `studio_id` output) |
| `EMR_STUDIO_BASIC_ROLE_ARN` | `tier_role_arns["basic"]` |
| `EMR_STUDIO_INTERMEDIATE_ROLE_ARN` | `tier_role_arns["intermediate"]` |

`EMR_STUDIO_URL` is unused in IAM mode. Role→tier mapping (in `notebook_service`):
`DataScientist → basic`; `TenantAdmin` / `PlatformAdmin → intermediate` (the
router already restricts launch to `TenantAdmin` / `DataScientist`).

## Switching between modes

`auth_mode` and `EMR_AUTH_MODE` are toggles; **IAM is now the default**, so set
both to `"SSO"` for the Identity Center path. The two modes are mutually
exclusive per Studio (the resource's `auth_mode` is immutable), so switching an
existing Studio means replacing it.

## Open items
- **MRM sign-off** on the attribution model above.
- **Studio region** — presign happens in `AWS_REGION`; if the Studio lives in a
  different region, that needs a region override (not yet parameterised).
- **`emr_serverless_runtime_role_arn_pattern`** defaults to `*`; scope it to the
  tenant execution-role pattern in production.
