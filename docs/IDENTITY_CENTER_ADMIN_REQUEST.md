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
- Confirmation that the groups above are visible in Identity Center as
  **groups** (not just as individual users), with their **exact identity
  names**. We reference those names verbatim in our EMR Studio session
  mappings, so any mismatch silently locks users out.

## What you do NOT need to do

- Create the EMR Studio resource itself.
- Create any session mappings, S3 buckets, or IAM roles.
- Generate or configure the Studio access URL.

All of the above is on the ML Platform team's side, via Terraform, once
Identity Center federation and group sync are in place.
