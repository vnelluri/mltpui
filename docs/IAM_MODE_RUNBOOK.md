# IAM-mode runbook — SAML federation, dataplane, Snowflake OBO, mitigations

The complete, ordered checklist for standing up EMR Studio in **IAM auth
mode** (the platform default — no Identity Center), including the Snowflake
OBO identity plumbing and the notebook-secret mitigations. Owners per step.
Companion docs: [EMR_STUDIO_IAM_MODE.md](EMR_STUDIO_IAM_MODE.md) (design),
[EMR_STUDIO_FEDERATION_REQUEST.md](EMR_STUDIO_FEDERATION_REQUEST.md) (the
Entra/IAM admin hand-off packet),
[EMR_STUDIO_AUTH0_SANDBOX.md](EMR_STUDIO_AUTH0_SANDBOX.md) (the ~$0
rehearsal), and [NOTEBOOK_SNOWFLAKE_OIDC.md](NOTEBOOK_SNOWFLAKE_OIDC.md).
SSO alternative: [SSO_MODE_RUNBOOK.md](SSO_MODE_RUNBOOK.md).

> Steps marked ✅ are already done in code on the current branches. Steps
> tagged **mode-independent** are identical under SSO mode.

## Phase 0 — Decisions (platform team)

1. Confirm **IAM mode** (the default): no Identity Center, no `sso:` calls
   (the permissions-boundary blocker never fires), sign-in via IAM SAML
   federation to Entra. Costs: an admin-created SAML provider + one Entra
   enterprise app, and SAML-cert rotation ownership (step 9).
2. Decide whether to run the **Auth0 sandbox rehearsal first**
   (recommended — Phase 1). It settles the open access-URL question and
   de-risks every admin hand-off for ~$0.

## Phase 1 — (Recommended) sandbox rehearsal (platform team, personal AWS acct)

3. Run [EMR_STUDIO_AUTH0_SANDBOX.md](EMR_STUDIO_AUTH0_SANDBOX.md)
   (~1h setup). Record the findings table — especially:
   - **Test #2 (raw access URL, unauthenticated)** — decides whether prod
     `EMR_STUDIO_URL` should be the Studio URL or the IdP-initiated URL
   - **Test #5 (PrincipalTag secret ABAC)** — validates the Tier-2
     mitigation's PassRole pattern before building it

## Phase 2 — Entra admin (part 1 — unblocks everything)

4. Create the **Studio SAML enterprise app** (non-gallery, or the "AWS
   Single-Account Access" gallery app): Identifier `urn:amazon:webservices`,
   Reply URL `https://signin.aws.amazon.com/saml`.
5. Export its **Federation Metadata XML** → send to the IAM admin.
6. **Snowflake OBO app client** — **mode-independent**: redirect URI
   `<PLATFORM_API_BASE_URL>/snowflake/oauth/callback`, expose the Snowflake
   scope (`SNOWFLAKE_OAUTH_SCOPE`), assign the `myapp-*` groups
   (assignment = who may mint tokens).
7. *(Recommended)* **SCIM Entra → Snowflake**: Snowflake users auto-created
   with `login_name` = UPN, auto-disabled on offboarding.

## Phase 3 — IAM admin (dataplane account)

8. Create the SAML provider from the metadata XML and return its **ARN**:
   ```bash
   aws iam create-saml-provider \
     --name ml-platform-emr-studio-entra \
     --saml-metadata-document file://metadata.xml
   ```
   One command, one output. Our stack deliberately has no
   `iam:*SAMLProvider` permissions.
9. **Ongoing ownership:** when Entra rotates its SAML signing certificate
   (~3 years), refresh with `aws iam update-saml-provider` — otherwise
   Studio sign-ins break. Calendar it.

## Phase 4 — Platform team: Terraform (`tmt-dataplane`) ✅ code-side

10. Apply with `auth_mode = "IAM"`, `saml_provider_arn = <step 8 ARN>`, and
    `tenant_role_permissions_boundary_arn = <org boundary ARN>` → the
    Studio, two SGs, service role, and the `basic`/`intermediate` **tier
    roles** (trusting the provider for `sts:AssumeRoleWithSAML` +
    `TagSession` + `SetSourceIdentity`). ✅ module ready.
11. ⚠️ **Live-account migration** (accounts that ran the old reconcile
    loop): `terraform state rm 'module.tenant'` **before** apply — orphans
    existing tenant resources to backend ownership instead of destroying
    them.
12. The apply also lands the **runtime role's provisioning grants** (ABAC
    create/teardown for tenant KMS/exec-role/EMR app, boundary deny-guard)
    ✅ committed (`tmt-dataplane` b5b2b2c).
13. Collect outputs → the **values packet** for the Entra admin:
    `emr_studio_url`, `emr_studio_saml_provider_arn`,
    `emr_studio_tier_role_arns` (template in the federation request doc).

## Phase 5 — Entra admin (part 2 — finish the app from the values packet)

14. **Relay State** = the Studio access URL (users land in the Studio, not
    the AWS console). If sandbox test #2 showed the raw access URL
    dead-ends for unauthenticated users, the backend's `EMR_STUDIO_URL`
    should instead be this app's **IdP-initiated URL** — decide here.
15. **Claims** (exact table in the federation request doc):
    `Role` = `"<tier-role-arn>,<provider-arn>"` per group;
    `RoleSessionName` = UPN (**must be stable** — it anchors Workspace
    ownership); `SourceIdentity` = UPN (CloudTrail);
    `PrincipalTag:email` = UPN (session tag for per-user ABAC — required by
    the notebook-secret design and Tier-2 mitigation); NameID persistent.
16. **Assign the existing groups** and map to tiers:
    `myapp-<tenant>-datascientist` → basic;
    `myapp-<tenant>-tenantadmin`, `myapp-platform-admin` → intermediate.
    Only assigned groups can federate — that is the access gate. No new
    groups, no SCIM to AWS, no changes to the Cognito app.

## Phase 6 — Platform team: backend config + deploy ✅ code-side

17. SSM params: `/ml-platform/emr/studio-url` (from step 13/14),
    `/ml-platform/entra/tenant-id`, `/ml-platform/snowflake/oauth-scope`.
18. Env: `EMR_AUTH_MODE=IAM` (default), `TENANT_ROLE_PERMISSIONS_BOUNDARY_ARN`
    (must equal the Terraform value — the deny-guard blocks CreateRole
    otherwise), `BACKEND_PRINCIPAL_ARN` (account split: backend task role,
    granted use of each tenant KMS key).
19. Redeploy the backend. The prod boot-guard refuses to start on any
    missing value — misconfiguration fails at deploy, not at click. ✅
20. Tenant lifecycle is now fully backend-owned ✅: `POST /tenants`
    provisions (EMR app with the interactive endpoint on, exec role, KMS
    key, S3 prefix), `POST /tenants/{id}/provision` retries,
    `DELETE /tenants/{id}` tears down (suspend first; KMS 30-day recovery;
    S3 kept unless `?deleteData=true`).

## Phase 7 — Snowflake admin (mode-independent)

21. Verify the **External OAuth integration** trusts Entra: issuer/JWKS,
    audience list includes the app URI, login claim → Snowflake user,
    `scp` → session role.
22. Run the role/warehouse grants from `setup_snowflake_integration.sql`
    (its custom-OAuth-client integration is superseded by External OAuth ✅
    documented).

## Phase 8 — Mitigations (same-tenant token-theft caveat, mode-independent)

Background: notebook kernels run on the attached EMR Serverless app under
the **tenant execution role** (shared per tenant) — the user's federated
session only drives the Studio UI. The Snowflake token is user-bound
(queries always attribute to its real owner; cross-tenant access is
impossible), but IAM alone cannot stop a same-tenant kernel reading a
colleague's secret. Layered response:

**Tier 1 — capability secrets ✅ implemented:**

23. ✅ Secret names random per session
    (`<job-token-prefix>snowflake-session/<uuid4>`), returned **once** in
    the launch response and shown once in the UI — the name is the
    capability (`routers/notebooks.py: mint_snowflake_session_secret`).
24. ✅ Tenant exec-role policy (provisioned by the backend):
    `GetSecretValue` on the prefix + `DeleteSecret` on the session
    subprefix, tenant-tag-conditioned; `ListSecrets` never granted.
25. ✅ Token self-expires (~60 min); helper cell deletes the secret after
    reading.

**Tier 2 — per-user runtime roles (follow-up; IAM mode is the clean case):**

26. Backend provisions `ml-platform-user-<email>-runtime` at first notebook
    launch (reusing the direct-boto3 provisioning machinery), scoped to that
    user's secret + tenant data — kernel identity becomes **the user**.
27. Tier-role `iam:PassRole` conditioned per user via the session tag from
    step 15: `…role/ml-platform-user-${aws:PrincipalTag/email}-runtime` —
    the Studio attach picker then shows each user exactly one role.
    (Unlike SSO mode, this works without caveats here — the SAML claim
    supplies the tag. Sandbox test #5 validates it.)
28. Offboarding cleanup (same `deprovision` pattern). Watch the IAM role
    quota (default 1000/account) past ~1000 users.

**Tier 3 — documented fallback:** device-code flow in the notebook (zero
stored secrets; Entra public-client app + kernel egress to
`login.microsoftonline.com`; interactive prompt per session).

## Phase 9 — Verify end to end

29. Open the deep-link URL as a test user → Entra sign-in → lands in the
    Studio, no `HashCsrf` / `AccessDenied` (the federation doc's verify
    section).
30. Unassigned user → cannot federate (denied at Entra).
31. Create a Workspace → `creatorUserId` = `<tier-role-id>:<UPN>`, stable
    across logins; a second user cannot manage it.
32. `POST /tenants` (real mode) → EMR app / exec role / KMS key appear in
    the dataplane account with `tenantId` tags; suspend → delete tears them
    down. (Mock-mode lifecycle already verified ✅ — 21/21 checks.)
33. Connect Snowflake in the UI → consent at Entra → launch a notebook →
    kernel fetches the session secret → query runs → **Snowflake query
    history shows the actual person**.
34. Cross-user secret read attempt fails (Tier 1: unguessable + List
    denied; Tier 2: IAM deny).
35. CloudTrail shows `SourceIdentity` = the user's UPN on
    `AssumeRoleWithSAML` and downstream calls.

## Phase 10 — Steady state

36. **Onboard a user** = add them to the right `myapp-*` group (Entra).
    Everything fans out: Studio federation, Snowflake token eligibility,
    (via SCIM) the Snowflake user.
37. **Onboard a tenant** = `POST /tenants` in the admin UI. No admin
    hand-offs, no Terraform.
38. **Offboard** = remove group membership (+ user disconnects or refresh
    token TTL-reaps); tenant deletion via the guarded `DELETE` flow.
39. **Watch:** SAML cert rotation (step 9), EMR Serverless app quota
    (~25/account — shard dataplane accounts past that), MRM sign-off on the
    federated-attribution model (still open).

---

**Critical path:** 4–5 → 8 → 10 → 13 → 14–16 → 17–19. The Snowflake track
(6–7, 21–22) and mitigations (23–25) parallelize. Everything ✅ is already
merged on `auth-cognito-saml` / `emr-studio-iam-mode` — the unticked steps
are admin hand-offs and deploys, not code.
