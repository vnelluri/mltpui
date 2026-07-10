# emr-studio/iac — Terraform module: EMR Studio (SSO auth mode)

Provisions the single, platform-global EMR Studio that the backend deep-links
into (`EMR_STUDIO_URL`, see `backend/app/services/notebook_service.py`). The
backend never calls the EMR Studio API itself — it only needs this module's
`url` output.

This is a **module** (no provider/backend blocks) — instantiate it from your
per-account pipeline root, e.g.:

```hcl
module "emr_studio" {
  source = "git::https://<host>/tmt.git//emr-studio/iac?ref=main"

  name_prefix         = "ml-platform"
  vpc_id              = var.vpc_id
  subnet_ids          = var.private_subnet_ids
  default_s3_location = "s3://ml-platform-artifacts-prod/emr-studio-workspaces"

  session_mappings = {
    "myapp-platform-admin"      = "intermediate"
    "myapp-team-a-datascientist" = "basic"
    "myapp-team-b-datascientist" = "basic"
  }
}

resource "aws_ssm_parameter" "emr_studio_url" {
  name  = "/ml-platform/emr/studio-url"
  type  = "String"
  value = module.emr_studio.url
}
```

## Prerequisites (out of scope for this module)

- **AWS IAM Identity Center must already be enabled** in this account/region,
  with your Entra ID tenant federated as an external IdP and SCIM-syncing the
  security groups documented in the platform README's naming convention
  (`myapp-platform-admin`, `myapp-{tenantId}-datascientist`, …). `auth_mode =
  "SSO"` depends on this; it is account-level AWS configuration, not
  something Terraform's `aws_emr_studio` resource can set up.
- `session_mappings` keys must match Identity Center identity **names**
  exactly (group names if `session_identity_type = "GROUP"`, the default).

## Known limitation (matches the platform README)

The Studio is **platform-global** while jobs/data are **per-tenant** — the
shared `user_role` and the two session policies (`basic`, `intermediate`)
grant EMR Serverless browse/attach and Workspace-bucket access, but cannot
scope S3 by tenant prefix the way per-tenant EMR Serverless execution roles
do for job submission. Per-tenant Studios are a later release; until then,
treat Studio-launched notebook access as platform-wide within whichever tier
a user's group is mapped to.

## What this module does NOT do

- Create or manage IAM Identity Center itself, its external IdP federation,
  or its users/groups.
- Create per-tenant EMR Serverless applications — those come from
  `tmt-dataplane`, same as job-submission compute (see `backend/iac/README.md`).
- Grant the backend any EMR Studio API permissions — the backend only reads
  the static URL from SSM and redirects the browser; no API calls happen
  against EMR Studio at request time.

## Resources created

- Two security groups (`engine`, `workspace`) wired per AWS's documented
  two-SG model (Workspace → Engine on 18888 only).
- A service role (assumed by the EMR Studio control plane) and a shared user
  role (assumed by federated sessions), each scoped to the Workspace S3
  location plus read/attach access to EMR Serverless.
- Two customer-managed session policies (`basic`, `intermediate`) used by
  `session_mappings`.
- The `aws_emr_studio` resource itself and its `aws_emr_studio_session_mapping`
  entries.

## Variables of note

- `default_s3_location` — where Workspace `.ipynb` files are stored; the
  module derives bucket/prefix from this for IAM scoping, so pass a real
  `s3://bucket[/prefix]` URI.
- `workspace_egress_cidrs` — defaults to `0.0.0.0/0` on 443 for the Workspace
  SG (Studio control plane, git, package indexes); restrict to your VPC
  endpoint / NAT ranges in production.
- `session_mappings` — `map(string)` of identity name → `"basic"` |
  `"intermediate"`. Empty by default; without at least one entry, nobody can
  open a session against the Studio.
