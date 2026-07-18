# SSO — Azure AD SAML via AWS Cognito + Amplify

The org-standard auth pattern: the React SPA signs in through the **Cognito
Hosted UI** (via AWS Amplify), Cognito federates to **Azure AD over SAML**,
and the backend validates the **Cognito ID token**. Supersedes the direct
Entra-OIDC design in [SSO_SETUP.md](SSO_SETUP.md).

## How it works

```
Browser (SPA, Amplify)      Cognito                     Azure AD
──────────────────────      ───────                     ────────
signInWithRedirect() ─────► Hosted UI /authorize
                            │ redirect to SAML IdP ───► Entra sign-in
                            │                           │ SAML response:
                            │ ◄─────────────────────────┘ email, givenname,
                            │   /saml2/idpresponse         groups (names)
                            │ maps attributes →
                            │ email / given_name / custom:groups
◄─────────────────────────  │ ?code=… back to the app
Amplify exchanges code
for Cognito JWTs            
                            
API calls: Authorization: Bearer <Cognito ID token>
                            
Backend validates: signature (user-pool JWKS), iss (user pool),
aud (app client), token_use == "id" → email, given_name,
custom:groups → memberships from the myapp-{tenant}-{role} convention
```

Key decisions:

- **The ID token is the Bearer credential** — user info (email, given name,
  groups) lives only there; Cognito access tokens carry no SAML-mapped
  attributes. The backend rejects access tokens (`token_use` check).
- **Group names travel in the token** as `custom:groups`, a comma-separated
  string of Azure AD group names mapped from the SAML groups claim. No
  Microsoft Graph calls, no client secret — the old OIDC path's GUID
  resolution and >200-group overage machinery is gone.
- **Role/tenant derivation is unchanged**: group names matching
  `myapp-{tenant}-{role}` (plus `myapp-platform-admin` / `myapp-platform-mrm`)
  become memberships, re-resolved on every request
  (`backend/app/services/membership_service.py`).

## Azure AD (identity team)

1. **Enterprise application** (non-gallery, SAML) — one per environment:
   - **Reply URL (ACS)**:
     `https://<cognito-domain>.auth.<region>.amazoncognito.com/saml2/idpresponse`
   - **Identifier (Entity ID)**: `urn:amazon:cognito:sp:<user-pool-id>`
2. **Claims**:
   - `email` → user's email
   - `givenname` → user's given name
   - **groups** → security groups, emitted as **names** (source attribute
     `sAMAccountName` for AD-synced groups; cloud-only groups emit GUIDs,
     which the convention parser will not match — use AD-synced groups or a
     claims-transformation policy that emits names)
   - Scope the groups claim to **groups assigned to the application** —
     SAML tokens omit the claim entirely above ~150 groups, and assigning
     only `myapp-*` groups keeps tokens small and membership deliberate.
3. **Assignment**: assign the `myapp-*` groups (or all users, with group
   claims filtered as above) to the enterprise application.
4. Hand back: the **federation metadata XML/URL** for the app.

## Cognito (self-service)

1. **User pool**:
   - Custom attribute **`custom:groups`** — String, max length **2048**
     (attributes are immutable after creation; size it generously). Mark it
     mutable so each sign-in refreshes it.
   - **Hosted UI domain** (e.g. `myapp.auth.us-east-1.amazoncognito.com`).
2. **SAML identity provider** (name it **`AzureAD`**, or set
   `VITE_COGNITO_SAML_PROVIDER` to whatever you choose):
   - Metadata: the Azure AD federation metadata URL/XML.
   - **Attribute mapping**:
     | SAML claim | User pool attribute |
     |---|---|
     | `http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress` | `email` |
     | `http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname` | `given_name` |
     | `http://schemas.microsoft.com/ws/2008/06/identity/claims/groups` | `custom:groups` |
   - Multi-valued SAML attributes are flattened by Cognito into one
     comma-separated string — exactly what the parsers on both sides expect
     (`parse_groups_claim` in `backend/app/auth/cognito.py`, mirrored in
     `frontend/src/auth/AuthContext.tsx`).
3. **App client** (public, no secret):
   - OAuth flow: **authorization code grant**; scopes `openid email profile`.
   - Identity provider: the SAML IdP only (disable the Cognito user directory
     unless you want local users).
   - Callback URLs: `https://<app-domain>` (+ `http://localhost:5173` for
     dev); sign-out URLs: `https://<app-domain>/login`.
   - Ensure the client can **read** `custom:groups`, `email`, `given_name`
     (attribute read permissions).
4. **ID token expiry**: default 60 min; Amplify silently refreshes using the
   refresh token, and membership is re-derived server-side on every request
   anyway.

## App configuration

Frontend (build-time `VITE_*` args — baked into the bundle):

| Variable | Value |
|---|---|
| `VITE_DEMO_MODE` | `false` |
| `VITE_COGNITO_USER_POOL_ID` | e.g. `us-east-1_AbCdEfGhI` |
| `VITE_COGNITO_CLIENT_ID` | the app client ID |
| `VITE_COGNITO_DOMAIN` | Hosted UI domain, **no scheme** |
| `VITE_COGNITO_SAML_PROVIDER` | IdP name (default `AzureAD`) |

Backend (SSM-injected in prod — see `backend/iac/main.tf`):

| Variable | SSM parameter |
|---|---|
| `COGNITO_USER_POOL_ID` | `/ml-platform/cognito/user-pool-id` |
| `COGNITO_APP_CLIENT_ID` | `/ml-platform/cognito/app-client-id` |
| `COGNITO_REGION` | *(env; blank → `AWS_REGION`)* |
| `AUTH_MODE` | `prod` |

Egress: the backend needs outbound 443 to
`cognito-idp.<region>.amazonaws.com` (JWKS, cached 15 min). The browser
talks to the Hosted UI domain and Azure AD on the user's own network.

## Code map

- `frontend/src/auth/amplifyConfig.ts` — Amplify/Cognito configuration,
  `DEMO_MODE`, SAML provider name.
- `frontend/src/auth/AuthContext.tsx` — `signInWithRedirect` /
  `fetchAuthSession` / `signOut`, Hub listener for the Hosted UI callback,
  `custom:groups` parsing, ID-token Bearer provider.
- `frontend/src/pages/LoginPage.tsx` — auto-initiates SSO for
  unauthenticated visitors in prod mode (silent when the Azure AD session
  is alive); the sign-in button remains as the fallback after an explicit
  sign-out or an SSO failure, so neither can loop back into sign-in.
- `backend/app/auth/cognito.py` — JWKS validation, `token_use=id`
  enforcement, `parse_groups_claim`.
- `backend/app/dependencies.py` — memberships from `payload.groups`,
  active-membership selection (unchanged).

## Consequences to be aware of

- **Snowflake token exchange**: `POST /snowflake/connect` forwards the
  user's bearer token to Snowflake's RFC 8693 exchange. The Snowflake
  **External OAuth security integration must now trust the Cognito user
  pool** (issuer/JWKS) instead of Entra, and map a claim to the Snowflake
  login name. Coordinate with the Snowflake admin before flipping prod.
- **Group changes still apply at next sign-in** (a new SAML assertion →
  fresh `custom:groups`), same as the old flow.
- **EMR Studio SSO is unrelated** to this flow — it authenticates via IAM
  Identity Center (see `EMR_STUDIO_LAUNCH.md`), not Cognito.

## Verification checklist

1. Sign in via the app → full-page redirect through the Hosted UI to Azure
   AD and back.
2. `GET /auth/token-info` in dev (or decode the ID token at jwt.io):
   confirm `token_use = "id"`, `aud` = app client ID, and `custom:groups`
   contains your comma-separated `myapp-…` names.
3. `GET /auth/me` returns the resolved role/tenant memberships.
4. Remove a user from a group → access reflects it on their next sign-in.
5. A user in no `myapp-*` group lands on the no-access page (403 from
   `/auth/me`).
