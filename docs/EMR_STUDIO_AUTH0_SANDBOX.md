# EMR Studio IAM-federation sandbox — personal AWS account + Auth0

A weekend-sized rehearsal of the production SAML design
([EMR_STUDIO_IAM_MODE.md](EMR_STUDIO_IAM_MODE.md) /
[EMR_STUDIO_FEDERATION_REQUEST.md](EMR_STUDIO_FEDERATION_REQUEST.md)) with
**Auth0 playing Entra** and your personal account playing the dataplane.
The SAML assertion shape is identical to what Entra will send — only the
admin console differs — so anything proven here transfers, and anything
that fails here would have failed the Entra admins too.

**What this settles before any corporate admin spends time:**

| # | Question | Feeds back into |
|---|---|---|
| 1 | Does access-URL → IdP → `AssumeRoleWithSAML` → hosted `CreateStudioPresignedUrl` → Workspace actually work end to end? | the whole design |
| 2 | What does the **raw access URL** do for an unauthenticated federated user — bounce to the IdP, or dead-end at generic AWS sign-in? (If the latter, prod `EMR_STUDIO_URL` should be the IdP-initiated URL.) | `EMR_STUDIO_URL` value, LAUNCH doc |
| 3 | Does `creatorUserId = ${aws:userId}` give durable per-user Workspace ownership across logins, with user B unable to manage user A's Workspace? | MRM attribution sign-off |
| 4 | Is the `#collab=…` fragment really dropped by the SAML POST hop? (Expected: yes — observe it once.) | EMR_STUDIO_LAUNCH.md caveat |
| 5 | Does the `PrincipalTag:email` session tag arrive and enforce the per-user secret ABAC from [NOTEBOOK_SNOWFLAKE_OIDC.md](NOTEBOOK_SNOWFLAKE_OIDC.md)? | notebook Snowflake secrets |
| 6 | Does CloudTrail show `SourceIdentity` on the federated session's calls? | MRM attribution sign-off |

**Cost:** ≈ $0. EMR Studio, Workspaces, IAM, SAML provider and Auth0's free
tier are all free; Secrets Manager is ~$0.40/secret-month (delete after).
Only *attaching compute* costs money — don't attach any; every test above
ends at the Workspace UI.

---

## Part 1 — Auth0 (≈30 min)

1. **Tenant + users.** Free tenant at auth0.com. Create two database users
   (e.g. `alice@sandbox.test`, `bob@sandbox.test`). On each user, set
   `app_metadata` → `{"tier": "basic"}` (give one `"intermediate"` later if
   you want to test tier differences).

2. **Application.** Create a Regular Web Application, then enable the
   **SAML2 Web App** addon. In the addon's settings JSON:

   ```json
   {
     "audience": "urn:amazon:webservices",
     "destination": "https://signin.aws.amazon.com/saml",
     "nameIdentifierFormat": "urn:oasis:names:tc:SAML:2.0:nameid-format:persistent",
     "signatureAlgorithm": "rsa-sha256",
     "digestAlgorithm": "sha256"
   }
   ```

   Set the addon's **Application Callback URL** to
   `https://signin.aws.amazon.com/saml`.

3. **Post-login Action** (Actions → Library → Build Custom → attach to the
   Login flow). This is Auth0's equivalent of Entra's claims mapping — the
   four attributes from the federation request doc:

   ```javascript
   exports.onExecutePostLogin = async (event, api) => {
     // Fill in after Part 2 emits the ARNs:
     const PROVIDER = "arn:aws:iam::<ACCOUNT>:saml-provider/emr-studio-auth0";
     const ROLES = {
       basic: "arn:aws:iam::<ACCOUNT>:role/emr-studio-basic",
       intermediate: "arn:aws:iam::<ACCOUNT>:role/emr-studio-intermediate",
     };
     const tier = event.user.app_metadata?.tier || "basic";
     const A = "https://aws.amazon.com/SAML/Attributes/";
     api.samlResponse.setAttribute(A + "Role", `${ROLES[tier]},${PROVIDER}`);
     api.samlResponse.setAttribute(A + "RoleSessionName", event.user.email);
     api.samlResponse.setAttribute(A + "SourceIdentity", event.user.email);
     api.samlResponse.setAttribute(A + "PrincipalTag:email", event.user.email);
     api.samlResponse.setAttribute(A + "SessionDuration", "3600");
   };
   ```

4. **Export metadata** — from the addon's *Usage* tab, or
   `https://<tenant>.auth0.com/samlp/metadata?connection=Username-Password-Authentication`.
   Save as `metadata.xml`.

Two URLs you'll use in Part 3:

- **IdP-initiated login:** `https://<tenant>.auth0.com/samlp/<client_id>?RelayState=<studio-access-url>`
- **Raw access URL:** the Studio's `Url` from Part 2

## Part 2 — AWS (≈30 min)

All in one region of your personal account.

1. **SAML provider** (the production IAM-admin step, done by you):

   ```bash
   aws iam create-saml-provider \
     --name emr-studio-auth0 \
     --saml-metadata-document file://metadata.xml
   ```

2. **Tier role** `emr-studio-basic` — trust policy (matches what the
   `tmt-dataplane` module builds: `AssumeRoleWithSAML` + `TagSession` +
   `SetSourceIdentity`):

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Principal": { "Federated": "arn:aws:iam::<ACCOUNT>:saml-provider/emr-studio-auth0" },
       "Action": ["sts:AssumeRoleWithSAML", "sts:TagSession", "sts:SetSourceIdentity"],
       "Condition": { "StringEquals": { "SAML:aud": "https://signin.aws.amazon.com/saml" } }
     }]
   }
   ```

   Permissions policy — AWS's documented **EMRStudio_Basic_User_Policy**
   (AWS docs: "Create permissions policies for EMR Studio users"), which
   includes the essential grant, **plus** the ABAC statement for test #5:

   ```json
   {
     "Effect": "Allow",
     "Action": "elasticmapreduce:CreateStudioPresignedUrl",
     "Resource": "arn:aws:elasticmapreduce:<REGION>:<ACCOUNT>:studio/*"
   },
   {
     "Effect": "Allow",
     "Action": "secretsmanager:GetSecretValue",
     "Resource": "arn:aws:secretsmanager:<REGION>:<ACCOUNT>:secret:ml-platform/snowflake/user/${aws:PrincipalTag/email}-*"
   }
   ```

3. **EMR Studio**, console quick-path: EMR → Studios → Create Studio →
   **IAM authentication**, default VPC + two subnets, let the console
   create the service role and security groups, any S3 bucket for
   workspace storage. Note the Studio's **access URL** and ARN. (Or point
   `tmt-dataplane/modules/emr-studio` at the account with
   `auth_mode = "IAM"` and the provider ARN — closer to prod, more setup.)

4. **Two test secrets** for the ABAC probe:

   ```bash
   aws secretsmanager create-secret \
     --name "ml-platform/snowflake/user/alice@sandbox.test" \
     --secret-string '{"access_token":"fake-alice"}'
   aws secretsmanager create-secret \
     --name "ml-platform/snowflake/user/bob@sandbox.test" \
     --secret-string '{"access_token":"fake-bob"}'
   ```

5. Paste the provider + role ARNs back into the Auth0 Action (Part 1.3).

## Part 3 — Test matrix

Run in an incognito window per user. Record each row's outcome in the
findings table below.

| # | Test | Steps | Expected |
|---|---|---|---|
| 1 | **Happy path** | Open the IdP-initiated URL, sign in as alice | Lands in the Studio UI, no `HashCsrf` / `AccessDenied` |
| 2 | **Raw access URL, unauthenticated** | Fresh incognito → open the Studio access URL directly | *Open question.* Either it offers a federated path, or it dead-ends at generic AWS sign-in → prod must deep-link the IdP-initiated URL |
| 3 | **Workspace ownership** | As alice: create a Workspace; check its `creatorUserId` tag; sign out/in again; confirm she still owns it. As bob: try to open/delete alice's Workspace | Tag = alice's `aws:userId` (`<role-id>:alice@sandbox.test`), stable across logins; bob denied |
| 4 | **Collab fragment** | Open `<idp-initiated-url-RelayState-with>#collab=usecase:UC-1` (and also `<access-url>#collab=…` while already signed in) | Fragment **gone** after the SAML POST; **present** only on the already-authenticated direct navigation — confirming the LAUNCH.md caveat |
| 5 | **ABAC secret scoping** | In the Studio session as alice (CloudShell won't carry the tag — use a notebook cell or `aws` CLI with the federated session's creds): `get-secret-value` on alice's secret, then bob's | Alice's succeeds, bob's → `AccessDenied` — proves `PrincipalTag:email` arrived and the notebook-secret design enforces |
| 6 | **CloudTrail attribution** | After tests 1–5, CloudTrail → Event history, filter `AssumeRoleWithSAML` and `GetSecretValue` | `sourceIdentity: alice@sandbox.test` on the session and its calls |
| 7 | **SessionDuration** | Note session validity vs. the `3600` attribute | ~1h session |
| 8 | *(optional)* **Tier differences** | Set bob's `app_metadata.tier = "intermediate"`, add the second role | Bob sees start/stop application actions basic lacks |

### Findings

| # | Result | Date | Doc updated? |
|---|---|---|---|
| 1 | | | |
| 2 | | | *decides prod `EMR_STUDIO_URL` form* |
| 3 | | | |
| 4 | | | |
| 5 | | | |
| 6 | | | |

## Teardown

```bash
aws secretsmanager delete-secret --secret-id "ml-platform/snowflake/user/alice@sandbox.test" --force-delete-without-recovery
aws secretsmanager delete-secret --secret-id "ml-platform/snowflake/user/bob@sandbox.test" --force-delete-without-recovery
# Delete Workspaces, then the Studio, in the EMR console
aws iam delete-role-policy --role-name emr-studio-basic --policy-name ... && aws iam delete-role --role-name emr-studio-basic
aws iam delete-saml-provider --saml-provider-arn arn:aws:iam::<ACCOUNT>:saml-provider/emr-studio-auth0
# S3 bucket + Auth0 tenant can stay (free) or go
```

## What transfers to production, and what doesn't

| Piece | Transfers? |
|---|---|
| Assertion shape (Role, RoleSessionName, SourceIdentity, PrincipalTag:email, SessionDuration) | **1:1** — Entra sends the same claims, configured per the federation request doc |
| Trust + permissions policies, ABAC statement | **1:1** (module-built in prod) |
| Access-URL behavior finding (#2) | **1:1** — it's an AWS-side behavior |
| Fragment behavior (#4) | **1:1** — POST binding either way |
| Auth0 Action ↔ Entra claims UI | Console mechanics differ; semantics identical |
| Permissions boundary (`CSEStandardPermissionsBoundary`) | **Not reproduced** — personal accounts have none; irrelevant since prod avoids the boundary-blocked calls by design |

## Not covered here: the Snowflake OAuth flow

Auth0 rehearses the **SAML** half only. To rehearse the Snowflake
**OAuth** half (authorization-code + refresh, External OAuth), you need an
Entra-compatible OIDC issuer and a Snowflake account: a free Microsoft 365
developer / Entra test tenant + a Snowflake trial works, pointing the
backend's `ENTRA_TENANT_ID` / client / scope at the test tenant. Separate
exercise, separate write-up if needed.
