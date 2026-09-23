#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=dev-env.sh
source "${SCRIPT_DIR}/dev-env.sh"

if [[ ! -f "${REPO_ROOT}/.venv/bin/activate" ]]; then
  echo "Create venv at repo root: python3 -m venv .venv && pip install -e services/_shared -e 'services/pos[dev]' -e 'services/payments[dev]'"
  exit 1
fi
# shellcheck disable=SC1091
source "${REPO_ROOT}/.venv/bin/activate"

export POS_DB_ADMIN_URL
(cd "${REPO_ROOT}/services/pos" && alembic upgrade head)

export PAYMENTS_DB_ADMIN_URL
(cd "${REPO_ROOT}/services/payments" && \
  DATABASE_URL="postgresql+asyncpg://tillflow_payments:secret@127.0.0.1:${POS_DB_PORT}/tillflow" \
  alembic upgrade head)

echo "Migrations applied."
