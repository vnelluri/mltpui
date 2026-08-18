# Request: Enable IAM Identity Center for EMR Studio notebook access

> **Status: SSO-alternative packet — do not send while on IAM mode.** The
> platform currently defaults to **IAM auth mode**, which needs none of
> this (its hand-off is [EMR_STUDIO_FEDERATION_REQUEST.md](EMR_STUDIO_FEDERATION_REQUEST.md)).
> Send this packet only if the switch to SSO mode is decided — full
> sequence in [SSO_MODE_RUNBOOK.md](SSO_MODE_RUNBOOK.md).

**To:** AWS Organizations management-account admins
**From:** ML Platform team
**Scope:** Org-level AWS configuration only — the pieces Terraform cannot create.

## Context

Our ML platform deep-links users into a single EMR Studio for notebook
sessions. EMR Studio in SSO auth mode authenticates users through **IAM
Identity Center**, federated to our existing **Entra ID** tenant. This is
org-level AWS configuration that only your team can perform. It is:

- **separate** from the app's own login (which uses AWS Cognito), and
- **mostly separate** from the Terraform we run: we create the IAM roles,
  security groups, and session policies ourselves, and normally the EMR Studio
  resource and its session mappings too. The one exception is called out under
  "EMR Studio creation permissions" below — creating an SSO-mode Studio writes
  into *your* Identity Center instance, which our CI/CD role may not be allowed
  to do.

## What we need you to set up

1. **Confirm the IAM Identity Center instance and its home region.** A failed
   `CreateStudio` from our pipeline already references instance
   **`ssoins-72234c3bde346d6c`**, so an instance appears to be enabled in your
   org — we mainly need to know **which region it lives in**, because Identity
   Center has one home region per org and our dataplane pipeline must run in
   that same region to reference it. (Our platform otherwise runs in
   **`us-east-1`**; if the instance is elsewhere, that mismatch is the likely
   cause of the "resource does not exist in this Region" error we hit — see
   note below.) If no instance is in fact enabled, please **enable it** (a
   single-account AWS Organizations org is fine if we are not multi-account)
   and tell us the region.

   > **Region-mismatch symptom:** our `CreateStudio` failed with
   > *"…on resource `arn:aws:sso:::instance/ssoins-72234c3bde346d6c` because
   > the resource does not exist in this Region…"* — which happens when the
   > Studio is created in a different region than the Identity Center instance.
   > Confirming the instance's home region resolves this half of the error;
   > the permissions half is covered under "EMR Studio creation permissions".

2. **Federate Entra ID as the external identity provider.** Set up the
   SAML/OIDC trust between Identity Center and our Entra tenant. This is a
   **new, separate** enterprise app registration in Entra — please do **not**
   reuse the Cognito↔Entra SAML app the platform login uses; the two trusts
   are independent.

3. **Enable SCIM provisioning** from Entra into Identity Center, and sync the
   security groups below **by name** — the names must arrive exactly as
   written (not as GUIDs):

   | Group name |
   |---|
   | `myapp-platform-admin` |
   | `myapp-risk-analytics-tenantadmin` |
   | `myapp-risk-analytics-datascientist` |
   | `myapp-fraud-detection-tenantadmin` |
   | `myapp-fraud-detection-datascientist` |

   As we onboard more tenants we will ask you to sync additional
   `myapp-{tenant}-{role}` groups. `myapp-platform-mrm` does **not** need
   syncing — that role has no notebook access.

## What we need back from you

- The **home region** of instance `ssoins-72234c3bde346d6c` (per step 1), and
  whether it is administered from the **management account** or a
  **delegated-admin account**.
- **Confirmation that our dataplane account (`797771596368`) is a
  member of the same AWS Organization** as this Identity Center instance. Our
  EMR Studio session mappings reference your groups by name across accounts,
  which only works within one Organization — if the dataplane account is in a
  separate org, this approach does not work and we need to know before we
  build.
- Confirmation that the groups above are visible in Identity Center as
  **groups** (not just as individual users), with their **exact identity
  names**. We reference those names verbatim in our EMR Studio session
  mappings, so any mismatch silently locks users out.
- **Identity-store read access _or_ the stable group IDs.** To create a
  session mapping by group name, the role running our Terraform in the
  dataplane account must resolve each name to an Identity Center group ID
  against your identity store. Either grant that role identity-store read
  (`identitystore:ListGroups`, `identitystore:GetGroupId`) scoped to your
  instance, **or** hand us the stable **group IDs** for the groups above so we
  can reference them directly. Let us know which you prefer.
- **A change-notification agreement.** Because a rename or un-sync of any
  `myapp-*` group silently produces "no session" (no error) for affected
  users, please notify us before renaming, restructuring, or removing any of
  these groups so we can update our mappings in step.

## EMR Studio creation permissions (one decision we need from you)

Creating an EMR Studio in **SSO auth mode** is not purely an EMR action: the
`CreateStudio` API registers the Studio as a managed application **inside your
Identity Center instance**, so it calls `sso:CreateApplication` and
`sso:CreateManagedApplicationInstance` against your instance. Our dataplane
CI/CD role's permissions boundary currently **denies** those actions, so our
pipeline cannot create the Studio. We need you to pick one of:

- **Option A — grant the writes.** Allow our CI/CD role
  (`arn:aws:iam::797771596368:role/G-ROLE-AWS-ENTERPRISE-CICD`) to perform `sso:CreateApplication`,
  `sso:CreateManagedApplicationInstance` (and, for teardown,
  `sso:DeleteManagedApplicationInstance` / `sso:DeleteApplication`) on your
  instance and the `aws:applicationProvider/emrstudio` provider — scoped to
  that instance only. Then our pipeline creates the Studio as normal.
- **Option B — you create the Studio.** You (or whoever holds Identity Center
  write access) create the EMR Studio out-of-band, using the IAM role ARNs and
  security-group IDs we hand you from our Terraform, and return its **Studio ID
  and access URL**. Our pipeline runs with `create_studio = false` and manages
  everything else. This keeps org-level `sso:` writes off our CI/CD role.

Related but narrower: **session mappings** (which grant each group a `basic`/
`intermediate` tier) call `sso:CreateApplicationAssignment` + the identity-store
reads already requested above — *not* `CreateApplication`. If your boundary
denies only the Studio-creation writes, our pipeline can still own session
mappings; if it denies assignments too, you'd own those as well. Please tell us
which your boundary blocks.

### If we go with Option B: how to create the Studio

**Sequencing — you are waiting on us first.** We apply our Terraform with
`create_studio = false`, which creates the IAM roles, security groups, and
session policies but *not* the Studio. That apply produces the ARNs/IDs below;
we then send you this table filled in. **Do not create the Studio until you
have our values packet** — the roles and SGs must exist first.

Create one EMR Studio with these inputs (a single `CreateStudio` call):

| Input | Value | Source |
|---|---|---|
| Auth mode | **`SSO`** | you set this |
| Name | `ml-platform-studio` | our convention |
| Service role | *(ARN)* | our output `service_role_arn` |
| User role | *(ARN)* — **required in SSO mode** | our output `user_role_arn` |
| Engine security group | *(sg-…)* | our output `engine_security_group_id` |
| Workspace security group | *(sg-…)* | our output `workspace_security_group_id` |
| VPC | *(vpc-…)* | we provide |
| Subnets | *(subnet-…)* | we provide |
| Default S3 location | `s3://…/emr-studio-workspaces` | we provide |

> **Region:** create the Studio in the **same region as instance
> `ssoins-72234c3bde346d6c`** (per step 1). Creating it in another region is
> exactly the "resource does not exist in this Region" failure we already hit.

**The values packet we send you** — this is the whole handoff; we fill the
right-hand side in after our `create_studio = false` apply, then you create the
Studio from it:

```
EMR Studio to create (SSO mode):
  Name:                       ml-platform-studio
  Auth mode:                  SSO
  Region:                     <same region as ssoins-72234c3bde346d6c>
  Service role ARN:           <terraform output service_role_arn>
  User role ARN:              <terraform output user_role_arn>
  Engine security group:      <terraform output engine_security_group_id>
  Workspace security group:   <terraform output workspace_security_group_id>
  VPC ID:                     <our vpc_id>
  Subnet IDs:                 <our subnet_ids>
  Default S3 location:        s3://<bucket>/emr-studio-workspaces
```

CLI equivalent (same values):

```bash
aws emr create-studio \
  --name ml-platform-studio \
  --auth-mode SSO \
  --region <instance-region> \
  --vpc-id <vpc-id> \
  --subnet-ids <subnet-a> <subnet-b> \
  --service-role <service_role_arn> \
  --user-role <user_role_arn> \
  --engine-security-group-id <engine_sg_id> \
  --workspace-security-group-id <workspace_sg_id> \
  --default-s3-location s3://<bucket>/emr-studio-workspaces
```

**Return to us:** the `StudioId` and `Url` from the response. We plug those into
our pipeline (`studio_id` / `studio_url`), which wires the URL into the app and
creates the session mappings (if your boundary allows — see above). You do **not**
create session mappings or anything else under Option B; just the Studio.

## What you do NOT need to do

- Create the IAM roles, security groups, session policies, or S3 buckets — all
  ours, via Terraform.
- Create the EMR Studio resource **unless we pick Option B above**; by default
  it is ours to create.
- Generate or configure the Studio access URL (AWS emits it when the Studio is
  created; under Option B you return the value AWS gives you, nothing more).

Everything not listed under "EMR Studio creation permissions" is on the ML
Platform team's side, via Terraform, once Identity Center federation and group
sync are in place.

## Appendix: EMR Studio IAM policies (for reference only)

**You do not need to create these.** They are provisioned by our Terraform
module (`tmt-dataplane/modules/emr-studio`) in the account where the Studio lives, and
are included here only so you can review the access the platform grants. The
`Resource` ARNs below use our example Workspace bucket
(`s3://ml-platform-artifacts-prod/emr-studio-workspaces`); the module derives
the real bucket/prefix from its `default_s3_location` input.

Effective permissions for any session are the **intersection** of the user
role (assumed by every federated user) and the session policy mapped to that
user's group (`basic` or `intermediate`).

### Trust policy — service role and user role

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "elasticmapreduce.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

### 1. Service role — assumed by the EMR Studio control plane

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowEMRReadOnly",
      "Effect": "Allow",
      "Action": [
        "elasticmapreduce:ListInstances",
        "elasticmapreduce:DescribeCluster",
        "elasticmapreduce:ListSteps"
      ],
      "Resource": "*"
    },
    {
      "Sid": "AllowEC2ENIAndNetworkReadOnly",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeSubnets",
        "ec2:DescribeVpcs",
        "ec2:DescribeNetworkInterfaces",
        "ec2:CreateNetworkInterface",
        "ec2:CreateNetworkInterfacePermission",
        "ec2:DeleteNetworkInterface"
      ],
      "Resource": "*"
    },
    {
      "Sid": "AllowWorkspaceBucketList",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::ml-platform-artifacts-prod"
    },
    {
      "Sid": "AllowWorkspaceBucketObjects",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:GetEncryptionConfiguration"
      ],
      "Resource": "arn:aws:s3:::ml-platform-artifacts-prod/emr-studio-workspaces/*"
    }
  ]
}
```

### 2. User role — assumed by every federated SSO user (shared, platform-global)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowStudioSelfService",
      "Effect": "Allow",
      "Action": [
        "elasticmapreduce:DescribeStudio",
        "elasticmapreduce:ListStudios",
        "elasticmapreduce:DescribeCluster",
        "elasticmapreduce:ListInstances",
        "elasticmapreduce:ListSteps"
      ],
      "Resource": "*"
    },
    {
      "Sid": "AllowEmrServerlessBrowse",
      "Effect": "Allow",
      "Action": [
        "emr-serverless:ListApplications",
        "emr-serverless:GetApplication",
        "emr-serverless:ListJobRuns",
        "emr-serverless:GetJobRun"
      ],
      "Resource": "*"
    },
    {
      "Sid": "AllowWorkspaceBucketList",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::ml-platform-artifacts-prod"
    },
    {
      "Sid": "AllowWorkspaceBucketObjects",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::ml-platform-artifacts-prod/emr-studio-workspaces/*"
    }
  ]
}
```

### 3. Session policy — `basic` (DataScientist tier: attach + run notebooks)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BasicNotebookUsage",
      "Effect": "Allow",
      "Action": [
        "elasticmapreduce:DescribeStudio",
        "elasticmapreduce:DescribeCluster",
        "elasticmapreduce:ListInstances",
        "emr-serverless:ListApplications",
        "emr-serverless:GetApplication",
        "emr-serverless:GetJobRun"
      ],
      "Resource": "*"
    },
    {
      "Sid": "BasicWorkspaceStorage",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::ml-platform-artifacts-prod",
        "arn:aws:s3:::ml-platform-artifacts-prod/emr-studio-workspaces/*"
      ]
    }
  ]
}
```

### 4. Session policy — `intermediate` (TenantAdmin / PlatformAdmin tier: basic + app lifecycle)

`basic` plus the ability to start/stop the EMR Serverless applications a
Workspace attaches to:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BasicNotebookUsage",
      "Effect": "Allow",
      "Action": [
        "elasticmapreduce:DescribeStudio",
        "elasticmapreduce:DescribeCluster",
        "elasticmapreduce:ListInstances",
        "emr-serverless:ListApplications",
        "emr-serverless:GetApplication",
        "emr-serverless:GetJobRun"
      ],
      "Resource": "*"
    },
    {
      "Sid": "BasicWorkspaceStorage",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::ml-platform-artifacts-prod",
        "arn:aws:s3:::ml-platform-artifacts-prod/emr-studio-workspaces/*"
      ]
    },
    {
      "Sid": "IntermediateApplicationLifecycle",
      "Effect": "Allow",
      "Action": [
        "emr-serverless:StartApplication",
        "emr-serverless:StopApplication",
        "emr-serverless:StartJobRun",
        "emr-serverless:CancelJobRun"
      ],
      "Resource": "*"
    }
  ]
}
```
