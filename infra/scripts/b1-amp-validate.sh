#!/usr/bin/env bash
# B1 — generate edge traffic then query AMP for RED metrics (ADR-008).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REGION="${AWS_REGION:-us-west-1}"
WORKSPACE_ID="${AMP_WORKSPACE_ID:-ws-40261a89-bf51-45ee-a25b-e5fdfa21b69d}"

if ! python3 -c "import boto3" 2>/dev/null; then
  echo "AMP query needs boto3: pip install boto3  (or: deactivate and use system python3-boto3)" >&2
  exit 1
fi

# boto3 + `aws login` needs botocore[crt] unless we pass exported session keys into Python.
if [[ -z "${AWS_ACCESS_KEY_ID:-}" ]] && command -v aws >/dev/null 2>&1; then
  if creds="$(aws configure export-credentials --format env 2>/dev/null)"; then
    eval "$creds"
  fi
fi

if [[ -z "${API_ENDPOINT:-}" ]] && command -v terraform >/dev/null 2>&1; then
  API_ENDPOINT="$(terraform -chdir="${ROOT}/infra/envs/dev" output -raw api_endpoint 2>/dev/null || true)"
  export API_ENDPOINT
fi

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

echo "B1 script finished — look for non-zero values in result[] (or vector(0) placeholder when no series yet)."
