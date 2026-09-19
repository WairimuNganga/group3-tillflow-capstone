#!/usr/bin/env bash
# B1 — generate edge traffic then query AMP for RED metrics (ADR-008).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REGION="${AWS_REGION:-us-west-1}"
WORKSPACE_ID="${AMP_WORKSPACE_ID:-ws-40261a89-bf51-45ee-a25b-e5fdfa21b69d}"

echo "== Edge probe (synthetic traffic) =="
bash "${ROOT}/infra/scripts/reliability-edge-probe.sh"

echo "== Waiting for remote write scrape interval =="
sleep 20

echo "== AMP queries =="
query() {
  python3 "${ROOT}/infra/scripts/amp_promql_query.py" "$WORKSPACE_ID" "$1"
}

for svc in web payments pos; do
  echo "--- ${svc}_requests_total (instant) ---"
  query "sum(${svc}_requests_total) or vector(0)" | head -20
done

echo "B1 script finished — inspect JSON above; non-empty result[] means series reached AMP."
