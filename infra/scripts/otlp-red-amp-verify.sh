#!/usr/bin/env bash
# Generate non-probe HTTP traffic (ADR-008) and query AMP for RED metric names.
# Requires: aws login, boto3 (pip install boto3), API reachability.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REGION="${AWS_REGION:-us-west-1}"
WORKSPACE_ID="${AMP_WORKSPACE_ID:-ws-40261a89-bf51-45ee-a25b-e5fdfa21b69d}"

if ! python3 -c "import boto3" 2>/dev/null; then
  echo "Install boto3: pip install boto3" >&2
  exit 1
fi

if [[ -z "${AWS_ACCESS_KEY_ID:-}" ]] && command -v aws >/dev/null 2>&1; then
  if creds="$(aws configure export-credentials --format env 2>/dev/null)"; then
    eval "$creds"
  fi
fi

if [[ -z "${API_ENDPOINT:-}" ]] && command -v terraform >/dev/null 2>&1; then
  API_ENDPOINT="$(terraform -chdir="${ROOT}/infra/envs/dev" output -raw api_endpoint 2>/dev/null || true)"
  export API_ENDPOINT
fi

if [[ -z "${API_ENDPOINT:-}" ]]; then
  echo "Set API_ENDPOINT (terraform output api_endpoint, includes /v1)" >&2
  exit 1
fi

BASE="${API_ENDPOINT%/}"
query() {
  python3 "${ROOT}/infra/scripts/amp_promql_query.py" "$WORKSPACE_ID" "$1"
}

echo "== Non-probe traffic (counts toward RED; /health and /ready excluded) =="
# Paths hit ALB rules; 4xx/404 still increment {service}_requests_total when the app runs TelemetryMiddleware.
for _ in $(seq 1 15); do
  curl -sS -o /dev/null -w "." --max-time 10 -X POST "${BASE}/api/payments/stk" \
    -H "Content-Type: application/json" -d '{}' || true
  curl -sS -o /dev/null -w "." --max-time 10 "${BASE}/api/pos/sales" || true
done
echo ""

echo "== Wait for OTLP export (15s interval) + ADOT batch + AMP =="
sleep 45

echo "== AMP: total series =="
query 'count({__name__=~".+"})' | head -30

echo "== AMP: metric names matching *request* =="
query 'count by (__name__) ({__name__=~".*request.*"})' | head -40

for svc in payments pos web; do
  echo "== AMP: sum(${svc}_requests_total) =="
  query "sum(${svc}_requests_total) or vector(0)" | head -20
done

echo ""
echo "Done. If RED sums are still 0 but ecs_task_* exists, check:"
echo "  - Task image has TILLFLOW_TELEMETRY_EXPORT=otlp (Dockerfile.base)"
echo "  - ADOT sidecar tillflow4+ and metrics pipeline otlp -> prometheusremotewrite"
echo "  - Grafana Explore: {__name__=~\".*payments.*\"} for alternate OTLP naming"
