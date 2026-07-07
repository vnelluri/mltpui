# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# Multi-Tenant ML Training Platform — Backend image (FastAPI, Python 3.12)
# Three-stage build: base → dev → prod. No final stage runs as root.
# ─────────────────────────────────────────────────────────────────────────────

# ── base ─────────────────────────────────────────────────────────────────────
# Shared foundation: system deps, non-root user, dependency install.
FROM python:3.12-slim AS base

# Do not buffer stdout/stderr (better container logs); no .pyc files.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# curl is required by the HEALTHCHECK below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root runtime user. UID/GID 1000 matches typical host user for bind mounts.
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash appuser

WORKDIR /app

# Install Python dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install -r requirements.txt

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# ── dev ──────────────────────────────────────────────────────────────────────
# Target used by docker-compose. Hot reload via uvicorn --reload + bind mount.
# watchfiles gives uvicorn an efficient reloader; install it explicitly in case
# it is not pinned in requirements.txt.
FROM base AS dev

RUN pip install watchfiles

# Copy source so the image runs standalone; docker-compose bind-mounts over this
# for live editing, but a plain `docker build` still produces a runnable image.
COPY . .

RUN chown -R appuser:appuser /app
USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ── prod ─────────────────────────────────────────────────────────────────────
# Default target (used for ECS). Copies only the application source, no reloader.
FROM base AS prod

# Copy only what the app needs at runtime.
COPY ./app ./app
COPY ./scripts ./scripts

RUN chown -R appuser:appuser /app
USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
