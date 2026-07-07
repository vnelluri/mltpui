"""Run tokens: short-lived machine identity for training jobs.

A training job on EMR/SageMaker has no Entra user token, so without this it
cannot call the platform API at all (metric/param/tag logging). At job
submission a token bound to ``(tenantId, experimentId, runId)`` is minted:

- The opaque token (``mlrt_…``) travels to the job inside the per-job
  Secrets Manager secret — the same transit path as the Snowflake token.
  It is never returned by the API and never stored in plaintext.
- Only its SHA-256 hash is persisted (DynamoDB, TTL-expired shortly after
  the job's maximum runtime).
- ``get_current_user`` resolves a ``Bearer mlrt_…`` credential into a narrow
  machine principal that may only write to its own run — every other
  endpoint rejects it via the normal role guards.

This is deliberately the foundation for a future tmt-sdk
(``tmt.log_metric(...)``): the SDK just reads the secret and sends the
bearer token — no API redesign needed.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import settings
from app.db.models import RunToken, TrainingJob
from app.db.repositories.run_token_repo import RunTokenRepository

RUN_TOKEN_PREFIX = "mlrt_"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class RunTokenService:
    def __init__(self) -> None:
        self.repo = RunTokenRepository()

    def mint(self, job: TrainingJob) -> str:
        """Create and persist (hashed) a run token for a submitted job.

        Returns the plaintext token exactly once — the caller puts it in the
        per-job secret and must not store it anywhere else.
        """
        if not (job.experimentId and job.experimentRunId):
            raise ValueError("Job must be linked to an experiment run before minting.")
        token = RUN_TOKEN_PREFIX + secrets.token_urlsafe(32)
        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(hours=settings.RUN_TOKEN_TTL_HOURS)
        ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        self.repo.create(
            RunToken(
                tokenHash=_hash(token),
                jobId=job.jobId,
                experimentId=job.experimentId,
                runId=job.experimentRunId,
                tenantId=job.tenantId,
                expiresAt=expires_at,
            )
        )
        return token

    def resolve(self, token: str) -> Optional[RunToken]:
        """Return the RunToken for a presented credential, or None if it is
        unknown or expired (DynamoDB TTL deletion can lag, so expiry is also
        checked here)."""
        if not token.startswith(RUN_TOKEN_PREFIX):
            return None
        record = self.repo.get_by_hash(_hash(token))
        if record is None:
            return None
        cleaned = record.expiresAt.replace("Z", "+00:00")
        try:
            expires = datetime.fromisoformat(cleaned)
        except ValueError:
            return None
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(timezone.utc):
            return None
        return record


run_token_service = RunTokenService()
