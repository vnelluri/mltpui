# EMR Studio — IAM authentication mode (no Identity Center)

An alternative to the SSO/Identity Center design in
[EMR_STUDIO_LAUNCH.md](EMR_STUDIO_LAUNCH.md) and
[IDENTITY_CENTER_ADMIN_REQUEST.md](IDENTITY_CENTER_ADMIN_REQUEST.md). IAM mode
removes IAM Identity Center from the notebook path entirely.

## Why

Creating an EMR Studio in **SSO auth mode** makes `CreateStudio` register the
Studio as a managed application in IAM Identity Center — it calls
`sso:CreateApplication` / `sso:CreateManagedApplicationInstance`. Our dataplane
CI/CD role's permissions boundary (`CSEStandardPermissionsBoundary`) denies
those, so the SSO pipeline fails. IAM mode's `CreateStudio` makes **no `sso:`
calls**, so it doesn't hit that wall — and it needs no Entra↔Identity Center
federation through Identity Center, no SCIM group sync, and no session mappings.

## How access actually works (important — read before implementing)

**The backend does not presign EMR Studio.** In both auth modes it returns the
Studio's static **access URL** (`EMR_STUDIO_URL`) and lets AWS's hosted sign-in
flow authenticate the user and mint the presigned URL server-side.

Why not presign from the backend? The `CreateStudioPresignedUrl` operation —
though it exists as an AWS service API and an IAM action — is **not part of the
boto3/botocore SDK** (verified against the pinned `botocore==1.35.90` *and* the
latest release: the EMR client has `describe_studio`, `create_studio`, session
mappings, etc., but **no `create_studio_presigned_url`** and no presigned Studio
operation at all). It is invoked by the AWS console / hosted Studio layer, not
by third-party code. Attempting to call it from the backend either raises
`AttributeError` (stock SDK) or requires injecting an unpublished operation
model — brittle and unsupported. So we don't.

```
Browser                         Backend (control plane)        AWS-hosted EMR Studio
───────                         ───────────────────────        ─────────────────────
POST /notebooks/launch ───────► notebook_service.launch()
                                │ (no AWS API call)
◄── 201 { url = EMR_STUDIO_URL }┘
window.open(EMR_STUDIO_URL) ──────────────────────────────────► access URL
                                                                 │ redirects to
                                                                 │ IAM sign-in / your
                                                                 │ IdP (IAM federation)
      user authenticates ◄───────────────────────────────────────┘
                                                                 hosted flow calls
                                                                 CreateStudioPresignedUrl
                                                                 (authorized by the user's
                                                                  IAM permission) ─► Workspace
```

## Assigning a user (IAM mode) = an IAM grant

There are **no session mappings** in IAM mode. You "assign" a user by granting
their IAM identity `elasticmapreduce:CreateStudioPresignedUrl` **on the Studio's
ARN** (optionally narrowed by ABAC tags or `aws:SourceIdentity` for federation):

```json
{
  "Effect": "Allow",
  "Action": ["elasticmapreduce:CreateStudioPresignedUrl"],
  "Resource": ["arn:aws:elasticmapreduce:<region>:<account>:studio/<studio-id>"]
}
```

Removing a user = removing that grant. Tiering (`basic` / `intermediate`) is
expressed by *which* EMR-Studio permissions the user's IAM identity carries —
the same example policies AWS documents — not by anything the backend does.

## Per-user identity

Per-user Workspace ownership still holds, but the identity comes from **the
user's own federated session**, not the app:

- The user reaches the Studio through the access URL and authenticates as
  themselves (IAM user, or — for a workforce on Entra — via **IAM federation**:
  the access URL redirects to Entra SAML and the user assumes an IAM role with
  `aws:SourceIdentity` set to their identity).
- EMR Studio tags every Workspace with `creatorUserId = ${aws:userId}`, so each
  federated user owns the Workspaces they create; the tier policies scope
  collaboration with `creatorUserId = ${aws:userId}`.

**Prerequisite this imposes:** for per-user identity, the EMR Studio must be set
up for **IAM federation to Entra** (a SAML IAM identity provider + a role the
Studio access URL federates into). This is IAM-native and does **not** involve
Identity Center — but it is a real setup step, and it is what replaces the
earlier (unbuildable) "backend assumes a tier role and presigns" design.

### Attribution for MRM/governance
- "Who launched a session" lives in the app's own audit log
  (`notebook.launch` with `userId`) — mode-independent, the governance-grade
  record.
- In-Studio AWS API calls are attributed to the federated session (its
  `aws:SourceIdentity` / role-session identity) in CloudTrail.

## Backend config

| Setting | Value |
|---|---|
| `EMR_AUTH_MODE` | `IAM` (documents the Studio's mode; the launch path does **not** branch on it) |
| `EMR_STUDIO_URL` | the Studio's static **access URL** (`describe-studio` → `Url`, or the module's `url` output) |

`EMR_STUDIO_ID` and the `EMR_STUDIO_BASIC/INTERMEDIATE_ROLE_ARN` tier-role
settings were removed — the backend no longer presigns, so it needs neither the
Studio id nor any tier role to assume. The prod-config guard now simply requires
`EMR_STUDIO_URL` (both modes).

## Terraform (`tmt-dataplane/modules/emr-studio`)

`auth_mode = "IAM"` creates the Studio with `auth_mode = "IAM"`, the two
security groups, and the service role.

> **Pending module change (Option A):** the module still creates two assumable
> **tier roles** (`…-emr-studio-basic` / `…-emr-studio-intermediate`) from the
> old backend-presign design. Under Option A the backend never assumes them, so
> they are dead and should be **removed**; the module should instead expose the
> IAM-federation **user role** (trusted by the SAML IdP) that the Studio access
> URL federates into. Until that change lands, the tier roles are harmless but
> unused. The backend module (`backend/iac`) has already dropped
> `emr_studio_id` / tier-role variables and the `sts:AssumeRole` grant on them.

## Switching between modes

`auth_mode` / `EMR_AUTH_MODE` describe how the Studio authenticates users; the
backend behaves identically either way (deep-link `EMR_STUDIO_URL`). The two
modes are mutually exclusive per Studio (the resource's `auth_mode` is
immutable), so switching an existing Studio means replacing it.

## Open items
- **EMR Studio IAM federation to Entra** — the SAML IdP + user role that gives
  per-user identity. Prerequisite for Option A; not yet in the module.
- **Module cleanup** — remove the unused tier roles; add the federation user
  role (see "Pending module change" above).
- **MRM sign-off** on the federated-session attribution model.
