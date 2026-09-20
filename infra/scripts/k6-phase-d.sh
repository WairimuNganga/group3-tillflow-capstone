#!/usr/bin/env bash
# Phase D — baseline then soak (edge probes only). Do not run during spike tests.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
EVID="${ROOT}/evidence/reliability"

if [[ -z "${API_ENDPOINT:-}" ]] && command -v terraform >/dev/null 2>&1; then
  export API_ENDPOINT="$(terraform -chdir="${ROOT}/infra/envs/dev" output -raw api_endpoint)"
fi

if [[ -z "${API_ENDPOINT:-}" ]]; then
  echo "export API_ENDPOINT=\$(terraform -chdir=infra/envs/dev output -raw api_endpoint)" >&2
  exit 1
fi

if ! command -v k6 >/dev/null 2>&1; then
  echo "Install k6: https://grafana.com/docs/k6/latest/set-up/install-k6/" >&2
  exit 1
fi

MODE="${1:-baseline}"
case "$MODE" in
  baseline)
    echo "Running baseline.js (~14m) — copy summary into evidence/reliability/k6-analysis.md"
    k6 run -e API_ENDPOINT="$API_ENDPOINT" "${ROOT}/reliability/k6/baseline.js" \
      | tee "${EVID}/k6-baseline.log"
    ;;
  soak)
    echo "Running soak.js (~18m) — JSON artifact for k6-analysis.md"
    k6 run -e API_ENDPOINT="$API_ENDPOINT" \
      --summary-export "${EVID}/k6-soak.json" \
      "${ROOT}/reliability/k6/soak.js" | tee "${EVID}/k6-soak.log"
    ;;
  both)
    bash "$0" baseline
    bash "$0" soak
    ;;
  *)
    echo "Usage: $0 {baseline|soak|both}" >&2
    exit 1
    ;;
esac
