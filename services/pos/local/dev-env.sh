# Shared local G2 stack settings. Source from other scripts in this directory.
# POS uses DATABASE_URL (not POS_DATABASE_URL). Payments default port is 8080.

POS_DB_PORT="${POS_DB_PORT:-5440}"
POS_URL="${POS_URL:-http://127.0.0.1:8000}"
PAY_URL="${PAY_URL:-http://127.0.0.1:8080}"

_pos_local_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "${_pos_local_dir}/../../.." && pwd)"

export TILLFLOW_TELEMETRY_EXPORT="${TILLFLOW_TELEMETRY_EXPORT:-none}"
export POS_DB_ADMIN_URL="postgresql+asyncpg://tillflow:secret@127.0.0.1:${POS_DB_PORT}/tillflow"
export PAYMENTS_DB_ADMIN_URL="${POS_DB_ADMIN_URL}"

_pos_runtime_url="postgresql+asyncpg://tillflow_pos:pos_secret@127.0.0.1:${POS_DB_PORT}/tillflow"
_pay_runtime_url="postgresql+asyncpg://tillflow_payments:secret@127.0.0.1:${POS_DB_PORT}/tillflow"

# POS and Payments each set DATABASE_URL in run-*.sh (never use POS_DATABASE_URL).

export PAYMENTS_BASE_URL="${PAYMENTS_BASE_URL:-${PAY_URL}}"
export POS_BASE_URL="${POS_BASE_URL:-${POS_URL}}"
export MPESA_CALLBACK_SECRET="${MPESA_CALLBACK_SECRET:-local-dev-callback-secret}"
export MPESA_ADAPTER="${MPESA_ADAPTER:-fake}"
export CALLBACK_SECRET="${CALLBACK_SECRET:-${MPESA_CALLBACK_SECRET}}"
