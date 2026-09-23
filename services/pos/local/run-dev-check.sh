#!/usr/bin/env bash
# Quick sanity check before e2e (same URLs as run-e2e.sh).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=dev-env.sh
source "${SCRIPT_DIR}/dev-env.sh"

check() {
  local url="$1" label="$2"
  local code body
  body="$(mktemp)"
  code="$(curl -s -o "$body" -w '%{http_code}' "$url" 2>/dev/null || echo 000)"
  if [[ "$code" == "200" ]]; then
    echo "OK  ${label}  ${url}  HTTP ${code}"
  else
    echo "BAD ${label}  ${url}  HTTP ${code}  $(head -c 120 "$body")"
    rm -f "$body"
    return 1
  fi
  rm -f "$body"
}

check "${POS_URL}/ready" "POS"
check "${PAY_URL}/health" "Payments"
echo "Ready for: services/pos/local/run-e2e.sh"
