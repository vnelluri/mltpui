#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# One-command local dev setup for the ML Training Platform. Run from repo root.
#
#   ./scripts/dev.sh
#
# Everything runs in Docker — no Python/Node needed on the host. This script:
#   1. Verifies docker + docker compose are available.
#   2. Creates .env from .env.example on first run.
#   3. Builds and starts the full stack (localstack, dynamo-init, backend, frontend).
#   4. Waits for LocalStack and the backend to report healthy.
#   5. Prints how to use the running stack.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# Resolve repo root regardless of where the script is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

# ── Colors (fall back to empty strings if the terminal doesn't support them) ──
if [ -t 1 ]; then
  BOLD="$(printf '\033[1m')"; RED="$(printf '\033[31m')"; GREEN="$(printf '\033[32m')"
  YELLOW="$(printf '\033[33m')"; RESET="$(printf '\033[0m')"
else
  BOLD=""; RED=""; GREEN=""; YELLOW=""; RESET=""
fi

info()  { printf "%s\n" "$*"; }
ok()    { printf "%s✅ %s%s\n" "${GREEN}" "$*" "${RESET}"; }
warn()  { printf "%s⚠️  %s%s\n" "${YELLOW}" "$*" "${RESET}"; }
fail()  { printf "%s❌ %s%s\n" "${RED}" "$*" "${RESET}" 1>&2; }

# ── 1. Prerequisite checks ───────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
  fail "Docker is not installed or not on PATH."
  info "Install Docker Desktop (>=24): https://docs.docker.com/get-docker/"
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  fail "The Docker Compose plugin is not available ('docker compose')."
  info "Install / update Docker Desktop or the compose plugin: https://docs.docker.com/compose/install/"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  fail "Docker daemon is not running. Start Docker Desktop and retry."
  exit 1
fi

# ── 2. Bootstrap .env ────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  warn "No .env found — created one from .env.example. Edit it to change your demo role."
else
  info "Using existing .env"
fi

# ── 3. Build & start the stack ───────────────────────────────────────────────
info "${BOLD}Building and starting the stack (this can take a few minutes on first run)...${RESET}"
docker compose up --build -d

# ── 4a. Wait for LocalStack health (60s timeout) ─────────────────────────────
info "Waiting for LocalStack to become healthy"
LS_TIMEOUT=60
LS_ELAPSED=0
until curl -fs "http://localhost:4566/_localstack/health" >/dev/null 2>&1; do
  printf "."
  sleep 2
  LS_ELAPSED=$((LS_ELAPSED + 2))
  if [ "${LS_ELAPSED}" -ge "${LS_TIMEOUT}" ]; then
    printf "\n"
    fail "LocalStack did not become healthy within ${LS_TIMEOUT}s."
    info "Check logs with: docker compose logs localstack"
    exit 1
  fi
done
printf "\n"
ok "LocalStack is healthy"

# The dynamo-init container (KMS setup -> create tables -> seed) runs to
# completion via compose dependency ordering before backend starts.
info "Waiting for backend to become healthy (tables + demo data are seeded first)"
BE_TIMEOUT=90
BE_ELAPSED=0
until curl -fs "http://localhost:8000/health" >/dev/null 2>&1; do
  printf "."
  sleep 2
  BE_ELAPSED=$((BE_ELAPSED + 2))
  if [ "${BE_ELAPSED}" -ge "${BE_TIMEOUT}" ]; then
    printf "\n"
    fail "Backend did not become healthy within ${BE_TIMEOUT}s."
    info "Check logs with: docker compose logs backend    (and: docker compose logs dynamo-init)"
    exit 1
  fi
done
printf "\n"
ok "Backend is healthy"

# ── 5. Summary ───────────────────────────────────────────────────────────────
cat <<'EOF'

✅ ML Training Platform is running locally

Frontend:   http://localhost:3000
Backend:    http://localhost:8000
API docs:   http://localhost:8000/docs
LocalStack: http://localhost:4566

Demo credentials (AUTH_MODE=dev):
  Role:     PlatformAdmin  (change DEV_USER_ROLE in .env to switch)
  Tenants:  Risk Analytics · Fraud Detection · Compliance
  Users:    8 demo users seeded across 6 group mappings

Snowflake (SNOWFLAKE_MOCK_MODE=true):
  All Snowflake calls return mock data — no real Snowflake account needed.
  Mock databases: PROD_DB · DEV_DB · ANALYTICS_DB
  Mock schema: ML_FEATURES with tables TRANSACTION_FEATURES · CUSTOMER_FEATURES

To change your demo role:
  Edit DEV_USER_ROLE in .env, then: docker compose restart backend

To reset demo data:
  docker compose exec backend python scripts/reset_local_db.py

To stop:
  docker compose down
EOF
