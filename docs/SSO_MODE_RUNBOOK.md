# SSO-mode runbook — IdC, Studio replacement, Snowflake OBO, mitigations

The complete, ordered checklist for moving EMR Studio from IAM mode to **SSO
mode (IAM Identity Center)**, including the Snowflake OBO identity plumbing
and the notebook-secret mitigations. Owners per step. Companion docs:
[IDENTITY_CENTER_ADMIN_REQUEST.md](IDENTITY_CENTER_ADMIN_REQUEST.md) (the
org-admin hand-off packet), [EMR_STUDIO_IAM_MODE.md](EMR_STUDIO_IAM_MODE.md)
(the current default this replaces), and
[NOTEBOOK_SNOWFLAKE_OIDC.md](NOTEBOOK_SNOWFLAKE_OIDC.md) (the notebook
Snowflake design the mitigations harden).

> Steps marked ✅ are already done in code on the current branches. Steps
> tagged **mode-independent** are needed even if you stay on IAM mode.

## Phase 0 — Decisions (platform team)

1. Confirm going **SSO mode** — accepting the org-level IdC dependency,
   Studio replacement (`auth_mode` is immutable), and session-mapping
   upkeep. Staying on IAM mode makes Phases 1–4 unnecessary.
2. Pick the **Studio-creation path** (the permissions-boundary decision):
   - **Option A** — boundary exemption so our CI/CD role may call
     `sso:CreateApplication` / `sso:CreateManagedApplicationInstance`
   - **Option B** — the IdC admin creates the Studio from our values packet
     (`create_studio = false` path; fully scripted in the request doc)

## Phase 1 — IdC admin (org management account)

3. Confirm the Identity Center instance (`ssoins-72234c3bde346d6c`) and its
   **home region** — the Studio must be created in that region (a previous
   `CreateStudio` failed on exactly this mismatch).
4. Confirm the dataplane account (`797771596368`) is in the **same AWS
   Organization** as the instance.
5. Federate **Entra → Identity Center** (with the Entra admin — a new
   enterprise app; not the Cognito app, not the IAM-mode SAML app).
6. Enable **SCIM** Entra → IdC; sync `myapp-platform-admin` and every
   `myapp-<tenant>-tenantadmin` / `-datascientist` group **by exact name**
   (names must arrive verbatim, not as GUIDs).
7. Answer the Option A/B decision from step 2; for A, grant the `sso:`
   writes to the CI/CD role scoped to the instance.
8. Grant our Terraform role `identitystore:ListGroups` / `GetGroupId` — or
   hand over the **stable group IDs**.
9. Agree to **notify before renaming/un-syncing** any `myapp-*` group (a
   rename silently produces "no session" for affected users).

Hand-off packet: [IDENTITY_CENTER_ADMIN_REQUEST.md](IDENTITY_CENTER_ADMIN_REQUEST.md)
(includes the Option B CLI and values-packet template).

## Phase 2 — Entra admin

10. The IdC federation enterprise app + SCIM provisioning token (pairs with
    steps 5–6).
11. **Snowflake OBO app client** — **mode-independent**: redirect URI
    `<PLATFORM_API_BASE_URL>/snowflake/oauth/callback`, expose the Snowflake
    scope (`SNOWFLAKE_OAUTH_SCOPE`), assign the `myapp-*` groups
    (assignment = who may mint tokens).
12. *(Recommended)* **SCIM Entra → Snowflake** so Snowflake users are
    auto-created with `login_name` = UPN and auto-disabled on offboarding.

## Phase 3 — Platform team: Terraform (`tmt-dataplane`)

13. `module.emr_studio` with `auth_mode = "SSO"` (+ `create_studio = false`
    for Option B) → security groups, service role, the **shared user role**,
    and the `basic`/`intermediate` **session policies** (policy JSON is in
    the request doc's appendix).
14. Option B only: send the **values packet** (role ARNs, SG ids,
    VPC/subnets, default S3 location) from the apply outputs.
15. *(Option B)* IdC admin runs the single `CreateStudio` call → returns
    **Studio ID + access URL** → feed back via `studio_id` / `studio_url`.
16. Create **session mappings**: each synced group → its tier. Keys must
    match IdC identity names exactly; an empty map = nobody can start a
    session. (Needs step 8's grant or the group IDs. If the boundary also
    denies `sso:CreateApplicationAssignment`, the IdC admin owns these too.)

## Phase 4 — Platform team: backend config + deploy

17. SSM `/ml-platform/emr/studio-url` = the new Studio's access URL.
18. `EMR_AUTH_MODE=SSO` — documentation only; the launch path deep-links the
    same `EMR_STUDIO_URL` in both modes (no code branch).
19. Snowflake env — **mode-independent** (✅ code-side): SSM
    `/ml-platform/entra/tenant-id`, `/ml-platform/snowflake/oauth-scope`,
    `SNOWFLAKE_OAUTH_CLIENT_ID/SECRET`.
20. Redeploy the backend.

## Phase 5 — Snowflake admin (mode-independent)

21. Verify the **External OAuth integration** trusts Entra: issuer/JWKS,
    audience list includes the app URI, login claim → Snowflake user,
    `scp` → session role.
22. Run the role/warehouse grants from `setup_snowflake_integration.sql`
    (its custom-OAuth-client integration is superseded by External OAuth ✅
    documented).

## Phase 6 — Mitigations (same-tenant token-theft caveat)

Background: notebook kernels run on the attached EMR Serverless app under
the **tenant execution role** (shared per tenant) in *both* auth modes — the
user's federated session only drives the Studio UI. The Snowflake token is
user-bound (queries always attribute to its real owner; cross-tenant access
is impossible), but IAM alone cannot stop a same-tenant kernel reading a
colleague's secret. Hence, layered:

**Tier 1 — capability secrets (build into the notebook-secrets feature from
day one; never ship guessable names):**

23. Secret names are random per session
    (`ml-platform/snowflake/session/<uuid4>`), returned **once** in the
    launch response — the name is the capability.
24. Tenant exec-role policy: allow `secretsmanager:GetSecretValue` on the
    prefix, **explicit deny `secretsmanager:ListSecrets`** (no enumeration).
25. Short TTL (~15–60 min) + the helper cell deletes the secret after
    reading (defense-in-depth).

**Tier 2 — per-user runtime roles (follow-up; clean in IAM mode, verify for
SSO):**

26. Backend provisions `ml-platform-user-<email>-runtime` at first notebook
    launch (reusing the direct-boto3 tenant-provisioning machinery), scoped
    to that user's secret + tenant data. Kernel identity becomes **the
    user** — per-user secrets AND per-user CloudTrail from inside notebooks.
27. Studio-session `iam:PassRole` conditioned per user via a policy variable
    in the resource ARN
    (`…role/ml-platform-user-${aws:PrincipalTag/email}-runtime`) so the
    attach picker shows exactly one role.
28. ⚠️ **SSO caveat:** step 27 needs a per-user session tag. In IAM mode the
    SAML `PrincipalTag:email` claim provides it; whether IdC attributes
    propagate into Studio sessions is **unverified** — test before
    committing to Tier 2 under SSO. (IAM-mode verification is test #5 in
    [EMR_STUDIO_AUTH0_SANDBOX.md](EMR_STUDIO_AUTH0_SANDBOX.md).)
29. Offboarding cleanup for user roles (same `deprovision` pattern as
    tenants). Watch the IAM role quota (default 1000/account) past ~1000
    users.

**Tier 3 — documented fallback:** device-code flow in the notebook (zero
stored secrets; the user authenticates as themselves from the kernel).
Needs an Entra public-client app + kernel egress to
`login.microsoftonline.com`; costs an interactive prompt per session.

## Phase 7 — Verify end to end

30. Studio URL as a synced test user → IdC → Entra login → lands in the
    Studio with the right tier.
31. Un-mapped user → cleanly denied (no session, no error — by design).
32. Create a Workspace → `creatorUserId` = the IdC user; a second user
    cannot manage it.
33. Connect Snowflake in the UI → consent at Entra → launch a notebook →
    kernel fetches the session secret → query runs → **Snowflake query
    history shows the actual person**.
34. Attempt a cross-user secret read (Tier 1: unguessable name + List
    denied; Tier 2: IAM deny).
35. Token expiry mid-session → the refresh path re-mints without
    re-consent.

## Phase 8 — Decommission IAM mode

36. Delete the old Studio, the tier roles, the IAM SAML provider, and the
    Studio's Entra SAML enterprise app. **Keep** the Cognito app (platform
    login) and the Snowflake OBO app client (step 11) — different tracks.

---

**Critical path:** 3 → 5/6 → 7 → 13–16. Everything else parallelizes.
Steps 11, 19, 21–22 are needed even on IAM mode — they are the Snowflake
OBO track, which never touches the Studio's auth mode.
