#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Smoke tests for the ML Training Platform backend.
#
#   ./scripts/test-api.sh                 # tests http://localhost:8000
#   API_BASE=http://host:8000 ./scripts/test-api.sh
#
# In local dev (AUTH_MODE=dev) no auth headers are required — the backend injects
# a synthetic user from DEV_USER_* env vars. Requires curl + jq.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

API_BASE="${API_BASE:-http://localhost:8000}"

# ── Colors ───────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  GREEN="$(printf '\033[32m')"; RED="$(printf '\033[31m')"
  BOLD="$(printf '\033[1m')"; RESET="$(printf '\033[0m')"
else
  GREEN=""; RED=""; BOLD=""; RESET=""
fi

# ── Prerequisite tooling ─────────────────────────────────────────────────────
missing=0
if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required but not installed."
  echo "  macOS:         brew install curl"
  echo "  Debian/Ubuntu: sudo apt-get install -y curl"
  echo "  Windows:       bundled with Git Bash, or 'winget install curl.curl'"
  missing=1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required but not installed."
  echo "  macOS:         brew install jq"
  echo "  Debian/Ubuntu: sudo apt-get install -y jq"
  echo "  Windows:       winget install jqlang.jq"
  missing=1
fi
[ "${missing}" -eq 1 ] && exit 1

PASS_COUNT=0
TOTAL_COUNT=0

# run_test <name> <method> <path> [json_body]
# Prints PASS/FAIL with HTTP status. A test passes when the status is 2xx.
run_test() {
  local name="$1" method="$2" path="$3" body="${4:-}"
  TOTAL_COUNT=$((TOTAL_COUNT + 1))

  local resp status
  if [ -n "${body}" ]; then
    resp="$(curl -s -w $'\n%{http_code}' -X "${method}" \
      -H "Content-Type: application/json" \
      -d "${body}" \
      "${API_BASE}${path}")"
  else
    resp="$(curl -s -w $'\n%{http_code}' -X "${method}" "${API_BASE}${path}")"
  fi

  status="$(printf "%s" "${resp}" | tail -n1)"
  local payload
  payload="$(printf "%s" "${resp}" | sed '$d')"

  if printf "%s" "${status}" | grep -qE '^2[0-9][0-9]$'; then
    printf "%s[PASS]%s %-40s %s %s (HTTP %s)\n" "${GREEN}" "${RESET}" "${name}" "${method}" "${path}" "${status}"
    PASS_COUNT=$((PASS_COUNT + 1))
    # Echo the created resource id when present (best-effort, non-fatal).
    printf "%s" "${payload}" | jq -e . >/dev/null 2>&1 || true
  else
    printf "%s[FAIL]%s %-40s %s %s (HTTP %s)\n" "${RED}" "${RESET}" "${name}" "${method}" "${path}" "${status}"
    # Show a short error snippet to aid debugging.
    local snippet
    snippet="$(printf "%s" "${payload}" | head -c 300)"
    [ -n "${snippet}" ] && printf "        response: %s\n" "${snippet}"
  fi
}

echo "${BOLD}Running API smoke tests against ${API_BASE}${RESET}"
echo

# Unique suffix so re-runs don't collide on unique keys.
SUFFIX="$(date +%s)"

# ── Health & auth ────────────────────────────────────────────────────────────
run_test "Health check"            GET  "/health"
run_test "Current user (auth/me)"  GET  "/auth/me"

# ── Tenants ──────────────────────────────────────────────────────────────────
run_test "Create tenant" POST "/tenants" \
  "{\"name\":\"Smoke Test Tenant ${SUFFIX}\",\"allowedFrameworks\":[\"pytorch\",\"xgboost\"],\"computeQuotaVcpuHours\":1000}"
run_test "List tenants"  GET  "/tenants"

# ── Snowflake connect (required before submitting a job with a Snowflake
#    data source — the backend needs a cached token to pass to the job) ──────
run_test "Connect to Snowflake" POST "/snowflake/connect"

# ── Jobs (exercises the mock Snowflake path via snowflake* fields) ───────────
# tenantId is required here because the default dev user is PlatformAdmin, who
# has no tenant of their own — tenant-scoped users (DataScientist) omit it.
run_test "Submit training job" POST "/jobs" \
  "{\"name\":\"smoke-job-${SUFFIX}\",\"tenantId\":\"tenant-risk-analytics\",\"computeType\":\"emr_serverless\",\"framework\":\"xgboost\",\"entryPointScript\":\"s3://ml-platform-artifacts/scripts/train.py\",\"s3InputPath\":\"s3://ml-platform-artifacts/input/\",\"instanceType\":\"ml.m5.xlarge\",\"instanceCount\":1,\"hyperparameters\":{\"max_depth\":\"6\",\"eta\":\"0.3\"},\"snowflakeDatabase\":\"PROD_DB\",\"snowflakeSchema\":\"ML_FEATURES\",\"snowflakeWarehouse\":\"COMPUTE_WH\"}"
run_test "List jobs" GET "/jobs"

# ── Experiments ──────────────────────────────────────────────────────────────
run_test "Create experiment" POST "/experiments" \
  "{\"name\":\"smoke-exp-${SUFFIX}\",\"tenantId\":\"tenant-risk-analytics\",\"description\":\"Smoke test experiment\",\"tags\":{\"team\":\"risk\"}}"
run_test "List experiments"  GET  "/experiments"

# ── Models ───────────────────────────────────────────────────────────────────
# artifactUri must point at a real object (registration trust) — use a
# seeded demo artifact.
run_test "Register model version" POST "/models" \
  "{\"name\":\"smoke-model-${SUFFIX}\",\"tenantId\":\"tenant-risk-analytics\",\"framework\":\"xgboost\",\"artifactUri\":\"s3://ml-platform-artifacts/tenant-risk-analytics/models/risk-score-model/v2/model.pkl\",\"description\":\"Smoke test model\"}"
run_test "List models" GET "/models"

# ── Group mappings / Snowflake / audit ───────────────────────────────────────
run_test "Snowflake status"    GET "/snowflake/status"
run_test "Audit events"        GET "/audit/events"

# ── Summary ──────────────────────────────────────────────────────────────────
echo
echo "${BOLD}${PASS_COUNT}/${TOTAL_COUNT} tests passed${RESET}"

if [ "${PASS_COUNT}" -ne "${TOTAL_COUNT}" ]; then
  exit 1
fi
