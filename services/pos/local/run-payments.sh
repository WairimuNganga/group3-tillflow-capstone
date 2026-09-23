#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=dev-env.sh
source "${SCRIPT_DIR}/dev-env.sh"

if ss -tln 2>/dev/null | grep -q ':8080 '; then
  echo "Port 8080 already in use. Run: ${SCRIPT_DIR}/stop-servers.sh"
  exit 1
fi

# shellcheck disable=SC1091
source "${REPO_ROOT}/.venv/bin/activate"

export DATABASE_URL="postgresql+asyncpg://tillflow_payments:secret@127.0.0.1:${POS_DB_PORT}/tillflow"
export POS_BASE_URL="${POS_URL}"
export MPESA_CALLBACK_SECRET
export MPESA_ADAPTER

echo "Payments on :8080, POS_BASE_URL=${POS_BASE_URL}, MPESA_ADAPTER=${MPESA_ADAPTER}"
cd "${REPO_ROOT}/services/payments"
exec uvicorn payments.main:app --host 127.0.0.1 --port 8080
