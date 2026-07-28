# Request: Entra enterprise app (SAML) for the platform login

**To:** Entra ID / IAM team
**From:** ML Platform team
**Scope:** One non-gallery SAML enterprise application per environment, that
AWS Cognito federates to for the app's own login.

## Context

The React app signs in through the **AWS Cognito Hosted UI**, which federates
to **Entra ID over SAML**; the backend validates the resulting Cognito ID
token (see [COGNITO_SAML_SSO.md](COGNITO_SAML_SSO.md)). We need you to create
the Entra side of that SAML trust.

This is a **non-gallery SAML enterprise application** — *not* an OIDC app
registration. There are no redirect URIs, no client secret, no API
permissions, and no exposed scopes; the trust is metadata + signing
certificate only.

> **Separate from EMR Studio.** This is independent of the Entra ↔ IAM
> Identity Center federation requested in
> [IDENTITY_CENTER_ADMIN_REQUEST.md](IDENTITY_CENTER_ADMIN_REQUEST.md). Same
> security groups, two independent trusts — please do **not** reuse one app
> for both.

## Prerequisite (on our side, before you build)

The two SP values below embed our Cognito user pool ID and Hosted UI domain,
which must exist first. We will hand you the concrete strings; until then the
`<…>` placeholders below show their shape. One enterprise app **per
environment** (`dev` / `prod`), because the entity ID is per-user-pool.

## What we need you to set up

Create a non-gallery SAML enterprise application with:

| Setting | Value |
|---|---|
| Identifier (Entity ID) | `urn:amazon:cognito:sp:<user-pool-id>` |
| Reply URL (ACS) | `https://<cognito-domain>.auth.<region>.amazoncognito.com/saml2/idpresponse` |
| Sign-on URL | *(blank — sign-in is always SP-initiated by Cognito)* |
| NameID | `user.mail`, format `emailAddress` |

**Claims:**

- `emailaddress` and `givenname` — Entra defaults are fine.
- **groups — emitted as NAMES, not object GUIDs.** Our backend matches
  literal group names (`myapp-platform-admin`, `myapp-{tenant}-{role}`) with
  no mapping table; a GUID matches nothing and silently drops the user to a
  no-access page.
- **Scope the groups claim to "groups assigned to the application."** Above
  ~150 group memberships Entra drops the groups claim from the SAML assertion
  entirely, and this design has no Microsoft Graph fallback. Restricting to
  app-assigned groups keeps tokens small and membership deliberate.

**Assign these groups to the application:**

| Group name |
|---|
| `myapp-platform-admin` |
| `myapp-platform-mrm` |
| `myapp-risk-analytics-tenantadmin` |
| `myapp-risk-analytics-datascientist` |
| `myapp-fraud-detection-tenantadmin` |
| `myapp-fraud-detection-datascientist` |

We will request additional `myapp-{tenant}-{role}` groups as tenants onboard.
(Unlike the EMR Studio request, `myapp-platform-mrm` **is** included here — it
is a valid app role, it just has no notebook access.)

## What we need back from you

- The **federation metadata URL**
  (`https://login.microsoftonline.com/<tenant-id>/federationmetadata/2007-06/federationmetadata.xml?appid=<app-id>`)
  — the **URL, not an exported XML file.** We configure Cognito with the URL
  so your token-signing certificate rollover doesn't cause a login outage.
- Confirmation that the groups claim emits **names** in this app (see the
  open question below).

## Open question that may change the design

**Are the `myapp-*` security groups cloud-only, or synced from on-prem AD?**
Emitting group *names* in a SAML assertion normally means source attribute
`sAMAccountName`, which Entra only offers for **AD-synced** groups. If these
groups are **cloud-only**, please confirm whether display names can still be
emitted (manifest `groupMembershipClaims: "ApplicationGroup"` plus the
`cloud_displayname` optional claim on the SAML2 token), or whether we need
AD-synced groups instead. This is the one answer that can invalidate our
group-name convention, so we need it before the user pool is built.

## Notes / standing requests

- **NameID = email is a deliberate, non-retroactive choice.** It becomes the
  Cognito federated username and cannot be changed after users exist. Please
  confirm every user in the groups above has `mail` populated, or their
  sign-in will fail.
- **Notify us before renaming or unassigning any `myapp-*` group.** Such a
  change silently drops affected users to a no-access page with no error
  anywhere in the stack.

## What you do NOT need to do

- Create any AWS resources (the Cognito user pool, app client, and SAML IdP
  are ours).
- Configure redirect URIs, client secrets, API permissions, or OAuth scopes —
  none apply to a SAML enterprise app.
- Anything related to EMR Studio / IAM Identity Center (separate request).
