# Notebook → Snowflake with the user's own identity (OIDC / OBO)

How a notebook running in EMR Studio connects to Snowflake **as the user who
launched it** — their Snowflake roles, their query history — with no shared
service account. Companion to [EMR_STUDIO_IAM_MODE.md](EMR_STUDIO_IAM_MODE.md)
and [EMR_STUDIO_FEDERATION_REQUEST.md](EMR_STUDIO_FEDERATION_REQUEST.md).

Status: **Tier 1 implemented** — the launch-time hook
(`routers/notebooks.py: mint_snowflake_session_secret`), the capability
secret (`job_service.store_snowflake_session_secret`), the exec-role
read/delete grants (`tenant_provisioning_service`), and the one-time UI
surfacing all exist in code. Tier 2 (per-user runtime roles) is roadmap;
its external dependency (the `PrincipalTag:email` SAML claim) is already in
the pending Entra federation request.

## The problem

Snowflake authorizes via OIDC (External OAuth, trusting Entra — our app client
is registered there). Inside a notebook the user's identity is an **AWS IAM
role session** (from `AssumeRoleWithSAML`, see EMR_STUDIO_IAM_MODE.md) — there
is no Entra token in the notebook, so the notebook cannot obtain a Snowflake
token by itself, and it cannot authenticate to our platform API either (the
API validates Cognito tokens — same problem, recursive).

What we do have:

- Per-user Entra-issued Snowflake tokens, minted by the backend via the
  **authorization-code + refresh** flow (`snowflake_service.py` —
  `build_authorize_url` / `redeem_auth_code` / `refresh_access_token`): the
  user consents once at Entra, and the KMS-encrypted **refresh token** in
  DynamoDB lets the backend re-mint access tokens *without the user
  present*. (This replaced an earlier pseudo-exchange that could never work
  in real mode — see "Seeding verdict" below.)
- A proven delivery path to dataplane compute: the per-job Secrets Manager
  TTL secret (`run_token_service.py`) that training jobs already read.

The design is just those two pieces, applied at notebook-launch time.

## Flow

```
User ── Entra login ──► Platform SPA (app client in Entra)
                          │ user's Entra-issued token
                          ▼
              POST /notebooks/launch (backend)
                          │ mint at Entra: redeem the user's stored
                          │ refresh token (from their one-time
                          │ authorization-code consent — "Connect
                          │ Snowflake" in the UI)
                          │ ◄─ Entra access token, aud = Snowflake app,
                          │     upn = the user
                          ▼
              Secrets Manager (dataplane account):
                <job-token-prefix>snowflake-session/<uuid4>
                          │  (random name returned ONCE in the launch
                          │   response — it IS the capability. Lives under
                          │   the job-token prefix so the runtime role's
                          │   ABAC create grant and the exec role's read
                          │   grant already cover it — no new IAM surface)
                          ▼
Notebook kernel — runs on the attached EMR Serverless app under the
TENANT EXECUTION ROLE (shared per tenant; NOT the user's federated
session — see "Trust boundary" below)
                          │ boto3 get_secret_value(<name from launch>)
                          │ → token; delete secret after read
                          ▼
              snowflake.connector.connect(authenticator="oauth", token=…)
                          ▼
              Snowflake External OAuth → validates against Entra
              (issuer, audience; upn → Snowflake user; scp → role)
              → queries run AS THE USER
```

Nothing changes on the Snowflake side: it validates the same Entra-issued
OBO tokens it already trusts.

## Trust boundary — what IAM can and cannot enforce here

**Correction to an earlier version of this design:** notebook code does not
run under the user's federated session. The Workspace UI does, but the
**kernel executes on the attached EMR Serverless application under the
tenant execution role** — a shared, per-tenant identity — in both Studio
auth modes. A per-user `${aws:PrincipalTag/email}` resource condition on
the *tier role* therefore never applies to kernel calls.

Consequences, stated precisely:

- **Attribution is never wrong.** The token's `upn` is baked in at mint —
  whoever presents it, Snowflake records the real owner and grants only
  that user's access. Cross-tenant theft is impossible (per-tenant secret
  prefix + per-tenant exec roles).
- **Same-tenant token borrowing is the residual risk**: IAM alone cannot
  stop user B's kernel reading user A's secret when both kernels share the
  tenant exec role.

Layered mitigations (details + step numbers in
[IAM_MODE_RUNBOOK.md](IAM_MODE_RUNBOOK.md) Phase 8):

**Tier 1 — capability secrets (implemented):**
- Secret names are random per session
  (`<job-token-prefix>snowflake-session/<uuid4>`), returned **once** in the
  launch response — possession of the name is the capability, delivered over
  the same trusted channel as the session itself
  (`routers/notebooks.py: mint_snowflake_session_secret`; UI shows it once).
- Tenant exec-role policy (provisioned by `tenant_provisioning_service`):
  `GetSecretValue` on the prefix + `DeleteSecret` on the session subprefix,
  both ABAC-conditioned on the tenant tag — and **no
  `secretsmanager:ListSecrets` anywhere** (implicit deny; names stay
  unenumerable).
- The token inside self-expires (~60 min) + the helper deletes the secret
  after reading.

**Tier 2 — per-user runtime roles (the enforcement upgrade; roadmap):**
- Backend provisions `ml-platform-user-<email>-runtime` at first notebook
  launch (same direct-boto3 machinery as tenant provisioning), scoped to
  that user's secrets + tenant data.
- The tier role's `iam:PassRole` is conditioned per user via the
  `PrincipalTag:email` session tag —
  `…role/ml-platform-user-${aws:PrincipalTag/email}-runtime` — so the
  Studio attach picker offers each user exactly one runtime role. The
  kernel then IS the user: per-user secret isolation **and** per-user
  CloudTrail from inside notebooks. (This is where the SAML
  `PrincipalTag:email` claim earns its keep — on PassRole at attach time,
  not on kernel secret reads.) Clean in IAM mode; under SSO mode the
  per-user session tag is unverified.

**Tier 3 — fallback:** device-code flow in the notebook — the user
authenticates as themselves from the kernel; no stored secret exists at
all. Interactive prompt per session; needs an Entra public-client app +
kernel egress to `login.microsoftonline.com`.

## Token lifetime & refresh

Entra access tokens live ~60–90 minutes; notebook sessions run for hours.
Because the backend holds a KMS-encrypted **refresh token** (from the
`offline_access` consent), it can re-mint **without the user present** —
so background refresh is available from day one: rewrite the secret on a
schedule while a session is active, or lazily via a "Refresh Snowflake
token" UI action (user re-runs the helper cell).

The notebook only ever sees short-lived access tokens — never a refresh
token.

## Notebook helper (what users paste in a cell)

```python
import boto3, json, snowflake.connector

def snowflake_conn(secret_name):
    """secret_name: shown once in the platform UI when you launch —
    random per session, expires in minutes, deleted after this read."""
    sm = boto3.client("secretsmanager")
    tok = json.loads(sm.get_secret_value(SecretId=secret_name)["SecretString"])
    try:
        sm.delete_secret(SecretId=secret_name, ForceDeleteWithoutRecovery=True)
    except Exception:
        pass  # best-effort; the TTL reaps it anyway
    return snowflake.connector.connect(
        account=tok["account"], authenticator="oauth", token=tok["access_token"])
```

(Ships later as part of the tmt-sdk alongside `tmt.log_metric` — same
secret-transit foundation, see `run_token_service.py`.)

## Governance properties

- **No shared credential anywhere** — every Snowflake session is the user's
  own OIDC identity; Snowflake RBAC and query history attribute to them.
- **Three audit systems, one identity:** Snowflake query history (the user
  — always, the token guarantees it), our audit log (`notebook.launch` +
  token mint/refresh events), CloudTrail (`GetSecretValue` — by the tenant
  exec role under Tier 1, by the per-user runtime role under Tier 2).
- The secret value is the same class of material as the existing per-job
  Snowflake secret — TTL'd, KMS-encrypted, never logged.
- The Snowflake **role** the notebook gets is a launch-time decision (the OBO
  `scope` → Snowflake `scp` → role mapping) — it can be narrower than what
  the user gets in the web UI.

## Prerequisites

1. `PrincipalTag:email` claim + `sts:TagSession` trust — in the pending Entra
   federation request / emr-studio module. (Needed for the Tier-2 per-user
   PassRole condition, not for kernel secret reads.)
2. Secrets Manager + KMS **VPC endpoints** in the dataplane subnets the EMR
   Serverless interactive sessions use (same class of wiring as the 18888
   Studio↔Engine rule).
3. The secret lives in the **dataplane** account; the backend writes it
   cross-account via the runtime role, exactly like per-job secrets today
   (prefix addition, not a new path).
4. ✅ Backend: launch-time hook in `POST /notebooks/launch`
   (`mint_snowflake_session_secret` — mint + write the capability-named
   secret, return the name once; launch never fails on Snowflake problems).
5. ✅ Tenant exec-role policy (`tenant_provisioning_service`):
   `GetSecretValue` on the job-token prefix + `DeleteSecret` on the
   session subprefix (tenant-tag-conditioned); `ListSecrets` never granted.

## Seeding verdict (resolved)

The original open question — how the backend seeds the token mint — was
audited and the pre-existing code **could not work in real mode**: it fed
the *Cognito* ID token (which Entra will not accept as an assertion) into
an RFC 8693 exchange aimed at *Snowflake's* token endpoint (which does not
implement RFC 8693; External OAuth has no exchange step at Snowflake at
all). It had only ever run behind `SNOWFLAKE_MOCK_MODE=true` — the same
failure class as the EMR `CreateStudioPresignedUrl` presign bug.

Resolution: "Connect Snowflake" now runs a real Entra
**authorization-code** flow (confidential app client, scope = Snowflake app
scope + `offline_access`); the backend stores the KMS-encrypted refresh
token and mints access tokens from it at will. Consequence for this design:
**background refresh of notebook secrets works from day one.**

## Open items / to verify

- Secret TTL + cleanup cadence for orphaned session secrets (mirror the
  job-secret TTL approach; delete-after-read covers the common case).
- **Tier-2 rollout**: per-user runtime role provisioning + the per-user
  PassRole condition — validate the PassRole/attach-picker behavior in the
  sandbox first ([EMR_STUDIO_AUTH0_SANDBOX.md](EMR_STUDIO_AUTH0_SANDBOX.md)
  test #5), and verify per-user session tags before attempting it under
  SSO mode.
- MRM sign-off on the attribution chain — including the Tier-1 residual
  (same-tenant token borrowing possible until Tier 2; attribution itself
  is never wrong).
