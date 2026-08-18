"""Background refresh of notebook-session Snowflake capability secrets.

Entra access tokens live ~60–90 minutes; notebook sessions run for hours,
and after launch there is no live platform identity to re-mint with. This
is the piece that makes that irrelevant (docs/NOTEBOOK_SNOWFLAKE_OIDC.md,
"Token lifetime & refresh"): the stored, KMS-encrypted **Entra refresh
token** is the durable grant, so a timer can re-mint *on behalf of* each
user with no user present.

Every tick, for each active session younger than the max age that carries a
capability-secret name:

1. ``ensure_valid_cache_by_ids`` — refreshes the user's access token at
   Entra when it will not outlive the next tick (rotating the stored
   refresh token when Entra returns a new one).
2. Rewrite the session's capability secret **under its existing name** —
   the value the user pasted into their notebook keeps working, and a
   secret already consumed by the helper's delete-after-read is re-created.

Sessions whose user disconnected Snowflake (or whose refresh fails) are
skipped — their secret simply ages out. Multi-replica note: two backend
tasks refreshing the same user concurrently is benign (writes are
idempotent; Entra keeps the previous refresh token valid through a grace
window on rotation).

Mock mode: never started — mock tokens are fabricated at connect time and
there is nothing real to refresh.
"""
from __future__ import annotations

import logging
import threading

from app.config import settings
from app.db.repositories.notebook_repo import NotebookRepository

logger = logging.getLogger("ml_platform.session_refresh")

_stop = threading.Event()


def refresh_active_session_secrets() -> int:
    """One refresh pass. Returns how many session secrets were rewritten."""
    # Imported here (not module-level) so tests can monkeypatch the router
    # functions and to keep import order router→service one-directional.
    from app.routers.snowflake import ensure_valid_cache_by_ids
    from app.services.job_service import job_service
    from app.services.snowflake_service import KmsCipher

    repo = NotebookRepository()
    sessions = repo.list_active(settings.SNOWFLAKE_SESSION_REFRESH_MAX_AGE_HOURS)
    refreshed = 0
    for session in sessions:
        if not session.snowflakeSecretName or not session.tenantId:
            continue
        try:
            # Demand enough runway to outlive the next tick, so the secret
            # never holds a token that expires between passes.
            cache = ensure_valid_cache_by_ids(
                session.userId,
                session.tenantId,
                min_validity_seconds=(
                    settings.SNOWFLAKE_SESSION_REFRESH_INTERVAL_SECONDS + 120
                ),
            )
            token = KmsCipher(tenant_id=session.tenantId).decrypt(
                cache.snowflakeToken
            )
            job_service.store_snowflake_session_secret(
                session.tenantId,
                {
                    "account": settings.SNOWFLAKE_ACCOUNT or "",
                    "access_token": token,
                    "expiresAt": cache.expiresAt,
                    "username": cache.snowflakeUsername,
                },
                name=session.snowflakeSecretName,
            )
            refreshed += 1
        except Exception:
            # Disconnected user, revoked grant, transient AWS failure —
            # skip this session; the pass must never die on one row.
            logger.warning(
                "Session %s: Snowflake secret refresh skipped",
                session.sessionId,
                exc_info=True,
            )
    if refreshed:
        logger.info("Refreshed %d notebook Snowflake secret(s)", refreshed)
    return refreshed


def _loop() -> None:
    interval = settings.SNOWFLAKE_SESSION_REFRESH_INTERVAL_SECONDS
    while not _stop.wait(interval):
        try:
            refresh_active_session_secrets()
        except Exception:
            logger.exception("Session-secret refresh pass failed")


def start_session_refresher() -> None:
    """Start the daemon refresher thread (no-op in mock mode / when disabled)."""
    if settings.SNOWFLAKE_MOCK_MODE:
        return
    if settings.SNOWFLAKE_SESSION_REFRESH_INTERVAL_SECONDS <= 0:
        return
    threading.Thread(
        target=_loop, name="snowflake-session-refresher", daemon=True
    ).start()
    logger.info(
        "Snowflake session-secret refresher started (every %ss, max age %sh)",
        settings.SNOWFLAKE_SESSION_REFRESH_INTERVAL_SECONDS,
        settings.SNOWFLAKE_SESSION_REFRESH_MAX_AGE_HOURS,
    )
