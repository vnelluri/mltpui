# OBO flow walkthrough — how user identity reaches the kernel and Snowflake

The end-to-end sequence of the on-behalf-of flow: one user (Jane), one
launch, and the three artifacts that carry her identity. Companion to
[NOTEBOOK_SNOWFLAKE_OIDC.md](NOTEBOOK_SNOWFLAKE_OIDC.md) (the design and
trust analysis) — this doc is the narrative trace. Everything here is
implemented; code pointers at the bottom.

**The core insight:** the browser and the kernel are separated by a gap
nothing automatic can cross (no cookie, JWT, or session reaches a kernel —
only cell text does). The design bridges it with three artifacts, each with
one job:

- the **GRANT** (Entra refresh token) — authorizes *minting*; never leaves
  the backend
- the **TOKEN** (Entra access token, `upn` = the user) — authorizes
  *querying*; identity is inside it, Entra-signed
- the **NAME** (random capability, the secret's id) — authorizes *fetching*;
  the only thing the user carries across the gap, by pasting it

## The sequence

```
 Jane's Browser      Backend           Entra        Secrets Mgr      Studio UI       Kernel         Snowflake
──────────────      ───────           ─────        ───────────      ─────────       ──────         ─────────

═══ PHASE 0 · CONSENT (once per user) ══════════════════════════════════════════════════════════════════════
(1) Connect ───────► /snowflake/connect
(2) ◄─ authorizeUrl ─┘
(3) ── consent as Jane ─────────────► ✓
(4)                  ◄── callback: code (HMAC state + email binding checked)
(5)                  redeem code ───► issues GRANT
(6)                  GRANT stored (KMS, keyed userId)          ◄─── nothing leaves the backend, ever

═══ PHASE 1 · LAUNCH (live identity, ~1 second) ════════════════════════════════════════════════════════════
(7) Launch ────────► /notebooks/launch  (Cognito JWT → "this is Jane")
(8)                  exercise GRANT ──► mints TOKEN (upn=jane, exp≈60m)
(9)                  seal TOKEN + username ────► secret created under
                                                 random NAME (tag: tenantId)
(10) ◄── response: { studioUrl, NAME } ─┘        NAME persisted on session record (for step 16)

═══ PHASE 2 · THE HUMAN HOP (the only browser→kernel channel) ══════════════════════════════════════════════
(11) banner shows NAME once ── Jane copies it
(12) new tab ──────────────────────────────────────► SAML sign-in
                                                     (silent SSO, as Jane)
(13) Jane PASTES the NAME into a cell ─────────────────────────────► NAME arrives in kernel
        ▲ this paste is the entire bridge — no cookie, JWT, or session crosses; only cell text

═══ PHASE 3 · CONSUMPTION (kernel, tenant exec role) ═══════════════════════════════════════════════════════
(14)                                  get_secret_value(NAME) ◄────── kernel
                                      └► TOKEN + username released
                                         delete_secret(NAME)   (best-effort)
(15)                                                                 connect(token) ──► verifies upn
                                                                                        vs ENTRA keys
                                                                                        → session = JANE

═══ PHASE 4 · BACKGROUND (no identity, every 5 min, all day) ═══════════════════════════════════════════════
(16)                 refresher: for each active session with a NAME:
                     exercise GRANT ──► fresh TOKEN
                     re-create secret under the SAME NAME ──► ✓
(17) connection drops? Jane re-runs the cell (same NAME) ──────────► fresh TOKEN → still JANE

═══ PHASE 5 · DEATH ════════════════════════════════════════════════════════════════════════════════════════
(18) disconnect / group removal / 90d idle → GRANT gone → refresher skips → NAME dangles → TOKEN expires
```

## Jane's day, as she experiences it

```
9:00  click Launch → copy NAME from the banner → Studio tab opens (silent SSO)
9:02  paste NAME into the helper cell → connected as JANE
9:02–17:00  query freely; on any drop, re-run the same cell (same NAME)
            [refresher silently rewrites the secret every 5 minutes]
17:00+ walk away — token expires, session ages out, nothing to clean up
```

Total identity ceremony: **one copy, one paste, per session.**

## The three artifacts, traced

| Artifact | Born | Travels | Dies | Trust property |
|---|---|---|---|---|
| **GRANT** (refresh token) | consent (step 5) | **never** — KMS-encrypted in DynamoDB, backend-only | disconnect / revocation / ~90d idle TTL | the durable "on behalf of Jane"; only its *effects* travel |
| **TOKEN** (access, `upn=jane`) | steps 8 & 16, minted from the grant | backend → secret → kernel → Snowflake | ~60 min each | Entra-signed; identity is *inside* it — unforgeable, verified at the destination |
| **NAME** (capability) | step 9, `uuid4` | response → banner → **Jane's paste** → kernel | session age-out (12h) | unguessable + un-enumerable (`ListSecrets` never granted); possession = the right to the current token |

## How the kernel "gets the user" — two sentences

1. **The name gets there by hand**: delivered only to Jane's authenticated
   browser (step 10); her paste (step 13) is the sole channel across the
   browser→kernel gap — nothing else can cross it.
2. **The user gets there inside the token**: the secret's payload holds
   `username` (informational — for `print("connected as …")`) and the
   `upn`-bearing JWT (authoritative) — the kernel never needs to *be* Jane;
   it only needs to *present* something that provably is.

Kernel-side user info is never authoritative: Snowflake does not ask the
notebook who it is — it verifies Entra's signature on the `upn`. (On
SageMaker, `/opt/ml/metadata/resource-metadata.json` also exposes the
`UserProfileName` — informational only, same rule.)

## Defense in depth — what each layer's compromise buys (and doesn't)

- **NAME alone** (leaked after age-out): nothing to fetch.
- **NAME during the session** (a same-tenant kernel — the documented Tier-1
  residual): a ≤60-min token that still cannot exceed Jane's own Snowflake
  grants, and whose use attributes to Jane — *borrowing*, never
  misattribution; closed by Tier-2 per-user runtime roles.
- **TOKEN alone**: same bound — Jane's grants, ≤60 min, her name on every
  query.
- **GRANT**: unreachable from the dataplane entirely; revoking it kills
  every downstream artifact within one refresher tick + one token lifetime.

## Code pointers (the trace, verifiable)

| Step | Code |
|---|---|
| 1–6 consent | `routers/snowflake.py` — `snowflake_connect`, `snowflake_oauth_callback`, `_store_tokens`; `snowflake_service.py` — `make_oauth_state`/`verify_oauth_state`, `build_authorize_url`, `redeem_auth_code` |
| 7–10 launch | `routers/notebooks.py` — `launch_notebook`, `mint_snowflake_session_secret`; `routers/snowflake.py` — `ensure_valid_cache_by_ids`; `job_service.py` — `store_snowflake_session_secret` |
| 11 banner | `frontend/src/pages/workspace/NotebookPage.tsx` |
| 12 Studio SAML | not our code by design — `notebook_service.launch_emr_studio` returns the static URL; AWS's hosted flow + Entra do the rest |
| 13–15 kernel | the helper cell (see NOTEBOOK_SNOWFLAKE_OIDC.md); exec-role grants in `tenant_provisioning_service.py` (`JobTokenSecretsRead`, `SessionSecretDeleteAfterRead`, no `ListSecrets`) |
| 16–17 refresh | `services/session_refresh_service.py`; started from `app/main.py` |
| 18 death | `POST /snowflake/disconnect`; DynamoDB TTL on the cache row |
