#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=dev-env.sh
source "${SCRIPT_DIR}/dev-env.sh"

if ss -tln 2>/dev/null | grep -q ':8000 '; then
  echo "Port 8000 already in use. Run: ${SCRIPT_DIR}/stop-servers.sh"
  exit 1
fi

# shellcheck disable=SC1091
source "${REPO_ROOT}/.venv/bin/activate"

export DATABASE_URL="postgresql+asyncpg://tillflow_pos:pos_secret@127.0.0.1:${POS_DB_PORT}/tillflow"
export PAYMENTS_BASE_URL="${PAY_URL}"

echo "POS DATABASE_URL + PAYMENTS_BASE_URL=${PAYMENTS_BASE_URL}"
cd "${REPO_ROOT}/services/pos"
exec uvicorn pos.main:app --host 127.0.0.1 --port 8000
