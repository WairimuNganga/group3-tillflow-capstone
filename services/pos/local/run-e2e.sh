#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=dev-env.sh
source "${SCRIPT_DIR}/dev-env.sh"

export POS_URL PAY_URL CALLBACK_SECRET

wait_http() {
  local url="$1" label="$2"
  local i code
  for i in $(seq 1 45); do
    code="$(curl -s -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || echo 000)"
    if [[ "$code" == "200" ]]; then
      return 0
    fi
    sleep 1
  done
  echo ""
  echo "E2E aborted: ${label} not ready at ${url} (last HTTP ${code})."
  echo "Start both servers first (two terminals, leave them running):"
  echo "  services/pos/local/run-pos.sh"
  echo "  services/pos/local/run-payments.sh"
  echo "If ports are stuck: services/pos/local/stop-servers.sh"
  exit 1
}

wait_http "${POS_URL}/ready" "POS"
wait_http "${PAY_URL}/health" "Payments"

exec "${SCRIPT_DIR}/e2e-flow.sh"
