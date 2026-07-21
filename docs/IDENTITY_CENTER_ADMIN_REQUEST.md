# Request: Enable IAM Identity Center for EMR Studio notebook access

**To:** AWS Organizations management-account admins
**From:** ML Platform team
**Scope:** Org-level AWS configuration only — the pieces Terraform cannot create.

## Context

Our ML platform deep-links users into a single EMR Studio for notebook
sessions. EMR Studio in SSO auth mode authenticates users through **IAM
Identity Center**, federated to our existing **Entra ID** tenant. This is
org-level AWS configuration that only your team can perform. It is:

- **separate** from the app's own login (which uses AWS Cognito), and
- **separate** from any Terraform we run (we create the EMR Studio resource,
  its session mappings, and IAM roles ourselves, once your part is in place).

## What we need you to set up

1. **Enable IAM Identity Center** in the AWS Organizations management account
   (or a delegated-admin account), in region **`<our-region>`**. This
   requires an AWS Organizations org — a single-account org is fine if we are
   not multi-account.

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

- Confirmation that Identity Center is **enabled**, plus the **region** and
  whether it is the **management account** or a **delegated-admin account**.
- **Confirmation that our dataplane account (`<dataplane-account-id>`) is a
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

## What you do NOT need to do

- Create the EMR Studio resource itself.
- Create any session mappings, S3 buckets, or IAM roles.
- Generate or configure the Studio access URL.

All of the above is on the ML Platform team's side, via Terraform, once
Identity Center federation and group sync are in place.

## Appendix: EMR Studio IAM policies (for reference only)

**You do not need to create these.** They are provisioned by our Terraform
module (`backend/iac-emr-studio`) in the account where the Studio lives, and
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
