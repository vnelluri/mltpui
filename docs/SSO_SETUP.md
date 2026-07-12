# SSO Setup — Entra ID (OIDC) for mltpui, no Cognito

## The pattern and where to read about it

Official name (Microsoft docs): **"Single-page application signing in users + calling a protected web API"** on the **Microsoft identity platform**. Generic name: *OAuth 2.0 Authorization Code Flow with PKCE (SPA public client) + JWT-validating resource server*.

References to hand to an architect or search for:

- Microsoft Learn: <https://learn.microsoft.com/en-us/entra/identity-platform/scenario-spa-overview> (the SPA side)
- Microsoft Learn: <https://learn.microsoft.com/en-us/entra/identity-platform/scenario-protected-web-api-overview> (the API side — what our FastAPI backend implements)
- Official sample repo (same architecture, React + MSAL): <https://github.com/Azure-Samples/ms-identity-javascript-react-tutorial> — chapter 3 "Call your own API" is this codebase's shape
- Group claims: <https://learn.microsoft.com/en-us/entra/identity/hybrid/connect/how-to-connect-fed-group-claims>
- Standards: OAuth 2.0 (RFC 6749), PKCE (RFC 7636), JWT (RFC 7519), JWKS (RFC 7517), OAuth Security BCP (RFC 9700)

YouTube/blog search terms that hit this exact pattern:
`"React SPA MSAL Entra ID protected API"`, `"Microsoft identity platform SPA calling web API"`, `"FastAPI Azure AD JWT validation"`, `"auth code flow PKCE single page application"`.

Note: the "**ALB + Cognito + Azure AD SAML**" pattern you may find in AWS blogs is a *different* pattern (auth terminated at the load balancer, Cognito as SAML→JWT translator). We do not use it: our app performs OIDC directly against Entra and the ALB only forwards traffic.

## How it works (one paragraph for the ticket)

The React SPA (served from ECS behind an ALB) uses `@azure/msal-browser` to sign users in against Entra ID with the OIDC authorization-code + PKCE flow. Entra issues an access token containing the user's security-group memberships in the `groups` claim. The SPA sends that token as a `Bearer` header to the FastAPI backend, which validates the RS256 signature offline against Entra's published JWKS public keys, then maps group names (`myapp-{tenant}-{role}`) to application roles. AWS holds no identity trust with Azure; the only cross-cloud traffic is HTTPS to `login.microsoftonline.com` (public keys, cached) and optionally `graph.microsoft.com`.

---

## Entra ID side — raise with the cloud/identity team

### 1. App registration (single registration serves SPA + API)

| Setting | Value |
|---|---|
| Name | e.g. `ml-training-platform` |
| Platform | **Single-page application** (NOT "Web") — this enables auth code + PKCE, no client secret in browser |
| Redirect URIs | `https://<app-domain>` and `https://<app-domain>/login` (plus `http://localhost:5173` for dev if allowed) |
| Supported account types | Single tenant |

### 2. Expose an API (same registration)

| Setting | Value (must match code) |
|---|---|
| Application ID URI | `api://ml-training-platform` |
| Scopes | `ml-platform.read`, `ml-platform.write` (admin-consentable, "Admins and users") |
| Authorized client | the SPA client ID, pre-authorized for both scopes |

### 3. Token configuration — groups claim

- Add **groups claim** to both **ID token** and **access token**.
- Emit **security groups**; if groups are AD-synced, emit as **sAMAccountName** (names, not GUIDs) — the backend accepts both but names avoid Graph lookups.

### 4. Security groups + assignment

Create and populate groups following the naming convention (parsed by `backend/app/services/membership_service.py`):

- `myapp-{tenant}-TenantAdmin`, `myapp-{tenant}-DataScientist` — per tenant
- `myapp-platform-admin` (PlatformAdmin), `myapp-platform-mrm` (MRM)

### 5. Optional — Graph permission for group overage

Only needed if any user can be in **>200 groups** (token then omits the groups claim):

- Application permission `GroupMember.Read.All` with admin consent
- A **client secret** (or cert) for the backend to call Graph

### Values the cloud team must return to us

| Value | Goes into |
|---|---|
| Tenant ID | `ENTRA_TENANT_ID` (backend) + `VITE_ENTRA_TENANT_ID` (frontend) |
| Client ID | `ENTRA_CLIENT_ID` + `VITE_ENTRA_CLIENT_ID` |
| Client secret (only if Graph overage enabled) | `ENTRA_CLIENT_SECRET` via Secrets Manager |

---

## AWS side — self-service, no identity trust required

1. **ALB + DNS**: ACM certificate for `<app-domain>`, ALB with HTTPS listener using plain `forward` actions (no `authenticate-*` action, no Cognito) to two target groups → ECS frontend (:80) and backend (:8000, e.g. path `/api/*`). Route 53 alias `<app-domain>` → ALB.
2. **Backend task env** (`backend/app/config.py`):
   - `AUTH_MODE=prod`
   - `ENTRA_TENANT_ID=<tenant id>`
   - `ENTRA_CLIENT_ID=<client id>`
   - `ENTRA_AUDIENCE=api://ml-training-platform` (default already matches)
   - `ENTRA_CLIENT_SECRET` from Secrets Manager (only for Graph overage)
3. **Frontend build args**: `VITE_DEMO_MODE=false`, `VITE_ENTRA_TENANT_ID`, `VITE_ENTRA_CLIENT_ID` (redirect URI is `window.location.origin` — automatic).
4. **Egress**: ECS backend tasks need outbound 443 to `login.microsoftonline.com` (JWKS) and `graph.microsoft.com` (overage only). Browser traffic to Entra is the user's own network, not yours.
5. **CORS**: not needed if frontend and API share the ALB domain; if the API gets its own subdomain, allow the app origin in FastAPI CORS settings.

## Verification checklist

1. Sign in via the app → MSAL popup completes against Entra.
2. Decode the access token at `jwt.ms` (Microsoft's official token decoder) → confirm `aud = api://ml-training-platform` and `groups` contains your `myapp-…` names.
3. `GET /auth/me` returns the resolved role/tenant.
4. Remove a user from a group → access ends when the token expires (~1 h).

## Five questions to confirm with the enterprise architect

1. **App registrations vs SAML-only.** Does org policy allow creating a new Entra **app registration** with the *Single-page application* platform (public client, auth code + PKCE)? Or does the identity team only support SAML **Enterprise Applications**? (If SPAs/public clients are blocked by policy, this pattern is off the table regardless of technical merit.)
2. **Groups claim vs app roles.** Is emitting the **`groups` claim** in access tokens permitted, or does the org standard require **Entra app roles** instead (some orgs restrict group claims to limit directory data in tokens)? App roles would work too — the backend's group-name mapping would change to role-claim mapping, a contained code change.
3. **Cognito mandate.** Is there an organizational standard that all AWS-hosted applications must authenticate through **Cognito / a central broker**, or may an application validate Entra-issued JWTs directly? If Cognito is mandated, is that for governance (one federation trust) or a technical constraint we should know about?
4. **VPC egress.** Can the ECS backend tasks get **outbound HTTPS** to `login.microsoftonline.com` (JWKS) and `graph.microsoft.com` (group overage) — directly or via the corporate proxy? What is the exception process if the VPC is egress-locked?
5. **Consent and group ownership.** Will **admin consent** be granted for the API scopes (`ml-platform.read/.write`) and, if needed, the `GroupMember.Read.All` Graph permission? And can tenant admins be made **owners** of their `myapp-{tenant}-*` groups so day-to-day user onboarding doesn't require a ticket per user?
