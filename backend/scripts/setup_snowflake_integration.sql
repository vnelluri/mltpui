-- ============================================================================
-- ML Training Platform — Snowflake OAuth integration setup
--
-- Run once, as ACCOUNTADMIN, against your Snowflake account. This configures
-- Snowflake to trust the platform's Entra ID tenant as an OAuth authorization
-- server (via token-exchange, RFC 8693) so users' own Entra identity — not a
-- shared service account — is used for every Snowflake query and every
-- EMR/SageMaker job that reads from Snowflake.
--
-- After running this script, copy the CLIENT_ID / CLIENT_SECRET printed by
-- the final DESCRIBE statement into backend/.env (SNOWFLAKE_OAUTH_CLIENT_ID /
-- SNOWFLAKE_OAUTH_CLIENT_SECRET).
-- ============================================================================

USE ROLE ACCOUNTADMIN;

-- ── 1. Dedicated role for the platform ──────────────────────────────────────
-- A single Snowflake role the OAuth integration grants to authenticated
-- platform users. Keep this narrowly scoped — it is NOT a superuser role.
CREATE ROLE IF NOT EXISTS ML_PLATFORM_ROLE
    COMMENT = 'Role assumed by ML Training Platform users via Entra OAuth token-exchange.';

-- ── 2. Warehouse the platform queries run against ───────────────────────────
-- Sized small by default; the platform lets users pick a warehouse per query,
-- but this is the default referenced by SNOWFLAKE_DEFAULT_WAREHOUSE.
CREATE WAREHOUSE IF NOT EXISTS COMPUTE_WH
    WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'Default warehouse for ML Training Platform ad-hoc queries.';

GRANT USAGE ON WAREHOUSE COMPUTE_WH TO ROLE ML_PLATFORM_ROLE;

-- ── 3. Resource monitor — caps runaway ad-hoc query spend ───────────────────
CREATE RESOURCE MONITOR IF NOT EXISTS ML_PLATFORM_MONITOR
    WITH CREDIT_QUOTA = 100
    FREQUENCY = MONTHLY
    START_TIMESTAMP = IMMEDIATELY
    TRIGGERS
        ON 75 PERCENT DO NOTIFY
        ON 90 PERCENT DO NOTIFY
        ON 100 PERCENT DO SUSPEND;

ALTER WAREHOUSE COMPUTE_WH SET RESOURCE_MONITOR = ML_PLATFORM_MONITOR;

-- ── 4. Read grants on the databases/schemas the platform browses ────────────
-- Adjust these to your actual database/schema names — PROD_DB / ML_FEATURES
-- etc. are the names used by SNOWFLAKE_MOCK_MODE for local development so
-- the same names work in both modes if you create them for real.
GRANT USAGE ON DATABASE PROD_DB TO ROLE ML_PLATFORM_ROLE;
GRANT USAGE ON ALL SCHEMAS IN DATABASE PROD_DB TO ROLE ML_PLATFORM_ROLE;
GRANT SELECT ON ALL TABLES IN DATABASE PROD_DB TO ROLE ML_PLATFORM_ROLE;
GRANT SELECT ON FUTURE TABLES IN DATABASE PROD_DB TO ROLE ML_PLATFORM_ROLE;

-- ── 5. The OAuth security integration itself ────────────────────────────────
-- CUSTOM OAuth client type: Snowflake trusts Entra ID as the issuer and
-- validates the token-exchange grant per RFC 8693. OAUTH_REDIRECT_URI must
-- match the platform backend's token-exchange callback.
CREATE SECURITY INTEGRATION IF NOT EXISTS ml_platform_oauth
    TYPE = OAUTH
    OAUTH_CLIENT = CUSTOM
    OAUTH_CLIENT_TYPE = 'CONFIDENTIAL'
    OAUTH_REDIRECT_URI = 'https://<your-backend-domain>/snowflake/oauth/callback'
    OAUTH_ISSUE_REFRESH_TOKENS = TRUE
    OAUTH_REFRESH_TOKEN_VALIDITY = 7776000  -- 90 days
    OAUTH_ENFORCE_PKCE = TRUE
    PRE_AUTHORIZED_ROLES_LIST = ('ML_PLATFORM_ROLE')
    ENABLED = TRUE
    COMMENT = 'Trusts Entra ID as OAuth issuer; used for per-user token-exchange from the ML Training Platform backend.';

-- ── 6. Confirm the integration and retrieve client credentials ──────────────
-- Copy CLIENT_ID and (if shown) CLIENT_SECRET from this output into
-- backend/.env as SNOWFLAKE_OAUTH_CLIENT_ID / SNOWFLAKE_OAUTH_CLIENT_SECRET.
-- If the secret is not shown, regenerate it with:
--   SELECT SYSTEM$SHOW_OAUTH_CLIENT_SECRETS('ml_platform_oauth');
DESCRIBE SECURITY INTEGRATION ml_platform_oauth;
