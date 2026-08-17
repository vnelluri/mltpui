# Notebook → Snowflake with the user's own identity (OIDC / OBO)

How a notebook running in EMR Studio connects to Snowflake **as the user who
launched it** — their Snowflake roles, their query history — with no shared
service account. Companion to [EMR_STUDIO_IAM_MODE.md](EMR_STUDIO_IAM_MODE.md)
and [EMR_STUDIO_FEDERATION_REQUEST.md](EMR_STUDIO_FEDERATION_REQUEST.md).

Status: **design** — not yet implemented. The one external dependency (an extra
SAML claim) is already folded into the pending Entra federation request so it
lands in the same admin pass.

## The problem

Snowflake authorizes via OIDC (External OAuth, trusting Entra — our app client
is registered there). Inside a notebook the user's identity is an **AWS IAM
role session** (from `AssumeRoleWithSAML`, see EMR_STUDIO_IAM_MODE.md) — there
is no Entra token in the notebook, so the notebook cannot obtain a Snowflake
token by itself, and it cannot authenticate to our platform API either (the
API validates Cognito tokens — same problem, recursive).

What we do have:

- `snowflake_service.exchange_token` — the backend already exchanges the
  user's Entra token for a per-user Snowflake OAuth token (RFC 8693 / Entra
  **on-behalf-of**), with tokens KMS-encrypted in DynamoDB.
- A proven delivery path to dataplane compute: the per-job Secrets Manager
  TTL secret (`run_token_service.py`) that training jobs already read.

The design is just those two pieces, applied at notebook-launch time.

## Flow

```
User ── Entra login ──► Platform SPA (app client in Entra)
                          │ user's Entra-issued token
                          ▼
              POST /notebooks/launch (backend — the one moment that has
                          │           BOTH the user's Entra identity and
                          │           the AWS delivery machinery)
                          │ OBO exchange at Entra:
                          │   assertion = user's token
                          │   scope     = Snowflake app scope (session:scope…)
                          │ ◄─ Entra access token, aud = Snowflake app,
                          │     upn = the user
                          ▼
              Secrets Manager (dataplane account):
                ml-platform/snowflake/user/<email>   (TTL, KMS-encrypted)
                          │
Notebook (user's tier-role session, ABAC-scoped — see below)
                          │ boto3 get_secret_value → token
                          ▼
              snowflake.connector.connect(authenticator="oauth", token=…)
                          ▼
              Snowflake External OAuth → validates against Entra
              (issuer, audience; upn → Snowflake user; scp → role)
              → queries run AS THE USER
```

Nothing changes on the Snowflake side: it validates the same Entra-issued
OBO tokens it already trusts.

## Per-user isolation = IAM ABAC, not convention

The Entra SAML app for EMR Studio sends one extra claim
(already in the federation request):

```
https://aws.amazon.com/SAML/Attributes/PrincipalTag:email = <user UPN/email>
```

and the tier roles' trust policy allows `sts:TagSession`. Every federated
notebook session then carries an `email` session tag that **the user cannot
choose or change**, and the tier-role permissions policy scopes secret reads
to it:

```json
{
  "Effect": "Allow",
  "Action": "secretsmanager:GetSecretValue",
  "Resource": "arn:aws:secretsmanager:<region>:<dataplane-acct>:secret:ml-platform/snowflake/user/${aws:PrincipalTag/email}-*"
}
```

(The trailing `-*` covers Secrets Manager's random ARN suffix.) User A's
session physically cannot read user B's token — enforced by AWS, not by
naming discipline.

## Token lifetime & refresh

Entra access tokens live ~60–90 minutes; notebook sessions run for hours.

- **MVP:** a "Refresh Snowflake token" action in the platform UI — the backend
  re-runs the OBO exchange and rewrites the secret; the user re-runs the
  helper cell. Expired token → clear Snowflake auth error → one click, one
  cell re-run.
- **Later:** background refresh while a session is active. Requesting
  `offline_access` in the OBO exchange yields a refresh token (KMS-encrypted
  in DynamoDB, as today), letting the backend re-mint **without the user
  present** and rewrite the secret on a schedule for sessions marked active.

Either way the notebook only ever sees short-lived access tokens — never a
refresh token.

## Notebook helper (what users paste in a cell)

```python
import boto3, json, snowflake.connector

def snowflake_conn():
    email = "<your email>"  # matches your login; readable only by your session
    sm = boto3.client("secretsmanager")
    tok = json.loads(sm.get_secret_value(
        SecretId=f"ml-platform/snowflake/user/{email}")["SecretString"])
    return snowflake.connector.connect(
        account=tok["account"], authenticator="oauth", token=tok["access_token"])
```

(Ships later as part of the tmt-sdk alongside `tmt.log_metric` — same
secret-transit foundation, see `run_token_service.py`.)

## Governance properties

- **No shared credential anywhere** — every Snowflake session is the user's
  own OIDC identity; Snowflake RBAC and query history attribute to them.
- **Three audit systems, one identity:** Snowflake query history (the user),
  our audit log (`notebook.launch` + token mint/refresh events), CloudTrail
  (`GetSecretValue` by the federated session with `SourceIdentity`).
- The secret value is the same class of material as the existing per-job
  Snowflake secret — TTL'd, KMS-encrypted, never logged.
- The Snowflake **role** the notebook gets is a launch-time decision (the OBO
  `scope` → Snowflake `scp` → role mapping) — it can be narrower than what
  the user gets in the web UI.

## Prerequisites

1. `PrincipalTag:email` claim + `sts:TagSession` trust — in the pending Entra
   federation request / emr-studio module (tier-role trust policy).
2. Secrets Manager + KMS **VPC endpoints** in the dataplane subnets the EMR
   Serverless interactive sessions use (same class of wiring as the 18888
   Studio↔Engine rule).
3. The secret lives in the **dataplane** account; the backend writes it
   cross-account via the runtime role, exactly like per-job secrets today
   (prefix addition, not a new path).
4. Backend: launch-time hook in `POST /notebooks/launch` (OBO + secret write),
   tier-role policy statement, refresh endpoint/action.

## Open items / to verify

- **OBO seeding** — OBO requires an *Entra-issued* assertion for our app
  client; a Cognito token cannot seed it. `exchange_token` already takes an
  Entra token, so confirm how the backend obtains it (SPA acquires it, or a
  stored refresh token is replayed). This decides whether background refresh
  (needs stored refresh tokens) is available from day one.
- Secret TTL + cleanup cadence for stale user secrets (mirror the job-secret
  TTL approach).
- MRM sign-off on the attribution chain (extends the EMR Studio federation
  sign-off already tracked in EMR_STUDIO_IAM_MODE.md).
