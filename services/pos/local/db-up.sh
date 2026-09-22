#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=dev-env.sh
source "${SCRIPT_DIR}/dev-env.sh"

cd "${SCRIPT_DIR}"
POS_DB_PORT="${POS_DB_PORT}" docker compose up -d
docker compose ps

INIT_SQL="${REPO_ROOT}/services/payments/local/init-db.sql"
if [[ -f "${INIT_SQL}" ]]; then
  echo "Applying payments roles/schema (safe to re-run; 'already exists' is OK)..."
  docker exec -i tillflow-pos-db psql -U tillflow -d tillflow < "${INIT_SQL}"
fi

echo "Postgres on 127.0.0.1:${POS_DB_PORT} (container tillflow-pos-db)."
