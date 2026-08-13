# EMR Studio — IAM federation to Entra (admin request)

What the Entra / IAM admins need to set up so platform users can open the
**IAM-auth-mode** EMR Studio as themselves. Companion to
[EMR_STUDIO_IAM_MODE.md](EMR_STUDIO_IAM_MODE.md); this is the identity bridge it
depends on. (SSO-mode alternative: [IDENTITY_CENTER_ADMIN_REQUEST.md](IDENTITY_CENTER_ADMIN_REQUEST.md).)

## The ask in one line

Federate our **Entra** tenant to the **dataplane AWS account** via SAML 2.0, so a
user who opens the EMR Studio access URL signs in through Entra and assumes an
IAM role scoped to their access tier — no IAM Identity Center, no per-user IAM
users, no `sso:` writes.

## Why this (not Identity Center)

Creating the Studio in SSO mode calls `sso:CreateApplication`, which our CI/CD
permissions boundary (`CSEStandardPermissionsBoundary`) denies. IAM mode makes
no `sso:` calls; the identity bridge is instead a standard **IAM SAML provider +
roles**, which is under our own control. The backend never calls the EMR Studio
API — it only deep-links the Studio access URL; **Entra + these roles do the
sign-in.**

## Who does what

| Side | Owner | Artifact |
|---|---|---|
| IAM SAML provider (AWS) | us (Terraform) or IAM admin | `aws_iam_saml_provider` from Entra metadata |
| Tier roles `…-emr-studio-basic` / `-intermediate` (AWS) | us (Terraform) | trust the SAML provider via `AssumeRoleWithSAML` |
| Entra enterprise app (SAML) | **Entra admin** | claims + group assignment + relay state |

Terraform (`tmt-dataplane/modules/emr-studio`) already creates the tier roles
and, given the metadata, the SAML provider. The **Entra-side app is the manual
part** described below.

## Bootstrap ordering (resolves the chicken-and-egg)

The role trust needs the SAML provider ARN; the Entra "Role" claim needs the
role ARNs. Do it in this order:

1. **Entra admin** creates the enterprise app and exports its **federation
   metadata XML** (App → Single sign-on → SAML → "Federation Metadata XML").
2. **We** apply the module with `emr_studio_saml_metadata_document` = that XML
   (or the IAM admin creates the SAML provider and gives us
   `emr_studio_saml_provider_arn`). Terraform emits three root outputs:
   - `emr_studio_url` — the Studio access URL
   - `emr_studio_saml_provider_arn`
   - `emr_studio_tier_role_arns` = `{ basic = <arn>, intermediate = <arn> }`
3. **We hand those three back to the Entra admin** to finish the app (below).
4. **We** set the backend's `EMR_STUDIO_URL` = `emr_studio_url`.

## Entra enterprise app — exact configuration

**Basic SAML:**
- **Identifier (Entity ID):** `urn:amazon:webservices`
- **Reply URL (ACS):** `https://signin.aws.amazon.com/saml`
- **Relay State:** the **Studio access URL** (`emr_studio_url`) — so after
  sign-in the user lands directly in the Studio.

**Attributes & claims:**

| Claim (name) | Value |
|---|---|
| `https://aws.amazon.com/SAML/Attributes/Role` | one value **per tier the user is entitled to**, format `"<role-arn>,<saml-provider-arn>"` — driven by group membership (see mapping) |
| `https://aws.amazon.com/SAML/Attributes/RoleSessionName` | user UPN / email — **must be stable per user** (it becomes `aws:userId` → the Workspace `creatorUserId`, so a user keeps ownership across logins) |
| `https://aws.amazon.com/SAML/Attributes/SourceIdentity` | user UPN / email — for CloudTrail attribution (the role trust allows `sts:SetSourceIdentity`) |
| NameID | persistent, user UPN / email |
| `https://aws.amazon.com/SAML/Attributes/SessionDuration` | optional, e.g. `3600` |

**Group → tier-role mapping** (the `Role` claim value per group):

| Entra group (our convention) | Assign role |
|---|---|
| `myapp-<tenant>-datascientist` | `emr_studio_tier_role_arns["basic"]` |
| `myapp-<tenant>-tenantadmin`, `myapp-platform-admin` | `emr_studio_tier_role_arns["intermediate"]` |

Assign only the groups that should reach notebooks; unassigned users can't
federate. A user in multiple groups gets multiple `Role` values and picks a tier
at sign-in.

## Values packet (fill in from the Terraform outputs)

```
Studio access URL (Relay State):  <emr_studio_url>
SAML provider ARN:                <emr_studio_saml_provider_arn>
basic role ARN:                   <emr_studio_tier_role_arns.basic>
intermediate role ARN:            <emr_studio_tier_role_arns.intermediate>

Role claim value, basic tier:         <basic-role-arn>,<saml-provider-arn>
Role claim value, intermediate tier:  <intermediate-role-arn>,<saml-provider-arn>
```

## Per-user identity & attribution

- Each user federates as themselves; `RoleSessionName` = their UPN makes
  `aws:userId` stable, so EMR Studio's `creatorUserId = ${aws:userId}` gives
  durable per-user Workspace ownership (the tier roles scope
  collaboration-management to `creatorUserId = ${aws:userId}`).
- In-Studio AWS calls are attributed to the federated session (`SourceIdentity`)
  in CloudTrail. "Who launched a session" also lives in the app audit log.
- Confirm this attribution model with MRM (same open item as the SSO path).

## How to verify

1. `aws emr describe-studio --studio-id <id> --query 'Studio.AuthMode'` → `IAM`.
2. Open `emr_studio_url` in a browser as a test user → redirects to Entra →
   after sign-in, lands in the Studio (no `HashCsrf`/`AccessDenied`).
3. Create a Workspace; confirm its `creatorUserId` tag = the test user's
   `aws:userId`, and that a second user cannot manage it.
4. CloudTrail shows the federated `SourceIdentity` on the Studio calls.

## Notes / caveats

- **Prefer an admin-created SAML provider referenced by ARN** if the CI/CD role
  can't `iam:CreateSAMLProvider` (the permissions boundary may deny it — the
  same class of block that pushed us off SSO). Pass
  `emr_studio_saml_provider_arn` instead of the metadata document.
- The Studio is **platform-global**; tiers are platform-wide within a user's
  tier (no per-tenant S3 scoping yet — a later release).
