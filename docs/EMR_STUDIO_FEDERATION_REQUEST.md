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
| IAM SAML provider (AWS) | **IAM admin** (out-of-band) | `aws_iam_saml_provider` from Entra metadata — gives us its ARN |
| Tier roles `…-emr-studio-basic` / `-intermediate` (AWS) | us (Terraform) | trust the SAML provider ARN via `AssumeRoleWithSAML` (+ `sts:TagSession`, `sts:SetSourceIdentity`) |
| Entra enterprise app (SAML) | **Entra admin** | claims + group assignment + relay state |

Our Terraform (`tmt-dataplane/modules/emr-studio`) **never creates the SAML
provider** — it has no `iam:CreateSAMLProvider` permission (a permissions
boundary may deny it, and it's a sensitive account-global identity resource).
The IAM admin creates it and we reference its ARN.

## Bootstrap ordering (resolves the chicken-and-egg)

The role trust needs the SAML provider ARN; the Entra "Role" claim needs the
role ARNs. Do it in this order:

1. **Entra admin** creates the enterprise app and exports its **federation
   metadata XML** (App → Single sign-on → SAML → "Federation Metadata XML").
2. **IAM admin** creates the IAM SAML provider from that metadata
   (`aws iam create-saml-provider --name ml-platform-emr-studio-entra
   --saml-metadata-document file://metadata.xml`) and gives us its **ARN**.
3. **We** apply the module with `emr_studio_saml_provider_arn` = that ARN.
   Terraform emits three root outputs:
   - `emr_studio_url` — the Studio access URL
   - `emr_studio_saml_provider_arn` (echoes the input, for the packet below)
   - `emr_studio_tier_role_arns` = `{ basic = <arn>, intermediate = <arn> }`
4. **We hand those back to the Entra admin** to finish the app (below), and set
   the backend's `EMR_STUDIO_URL` = `emr_studio_url`.

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
| `https://aws.amazon.com/SAML/Attributes/PrincipalTag:email` | user UPN / email — becomes an ABAC **session tag** (the role trust allows `sts:TagSession`); IAM policies use `${aws:PrincipalTag/email}` to scope per-user resources, e.g. the notebook Snowflake-token secret ([NOTEBOOK_SNOWFLAKE_OIDC.md](NOTEBOOK_SNOWFLAKE_OIDC.md)) |
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

- **The IAM admin owns the SAML provider.** Our pipeline/runtime roles have no
  `iam:*SAMLProvider` permission by design — the same class of block that pushed
  us off SSO (`sso:CreateApplication`) could deny `iam:CreateSAMLProvider`, and
  it's a sensitive account-global resource. We only reference its ARN.
- The Studio is **platform-global**; tiers are platform-wide within a user's
  tier (no per-tenant S3 scoping yet — a later release).
