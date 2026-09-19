#!/usr/bin/env bash
# Synthetic availability probe (B3) — public edge only, ADR-008 probe paths excluded from SLI.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REGION="${AWS_REGION:-us-west-1}"
NAME_PREFIX="${NAME_PREFIX:-devops-g3}"
STAGE_NAME="${API_STAGE_NAME:-v1}"

resolve_api_endpoint() {
  if [[ -n "${API_ENDPOINT:-}" ]]; then
    return 0
  fi
  if command -v terraform >/dev/null 2>&1; then
    API_ENDPOINT="$(terraform -chdir="${ROOT}/infra/envs/dev" output -raw api_endpoint 2>/dev/null || true)"
    if [[ -n "${API_ENDPOINT}" && "${API_ENDPOINT}" != "None" ]]; then
      return 0
    fi
  fi
  if ! command -v aws >/dev/null 2>&1; then
    return 1
  fi
  local api_id
  api_id="$(aws apigatewayv2 get-apis --region "$REGION" \
    --query "Items[?Name=='${NAME_PREFIX}-api'].ApiId | [0]" --output text 2>/dev/null || true)"
  if [[ -z "${api_id}" || "${api_id}" == "None" ]]; then
    return 1
  fi
  API_ENDPOINT="$(aws apigatewayv2 get-stages --region "$REGION" --api-id "${api_id}" \
    --query "Items[?StageName=='${STAGE_NAME}'].InvokeUrl | [0]" --output text 2>/dev/null || true)"
}

if ! resolve_api_endpoint; then
  :
fi

if [[ -z "${API_ENDPOINT:-}" || "${API_ENDPOINT}" == "None" ]]; then
  echo "Could not resolve API base URL (must include stage, e.g. .../v1)." >&2
  echo "  export API_ENDPOINT=\"\$(terraform -chdir=infra/envs/dev output -raw api_endpoint)\"" >&2
  echo "  Or: aws login, then re-run (needs apigateway:GET on ${NAME_PREFIX}-api in ${REGION})." >&2
  exit 1
fi

BASE="${API_ENDPOINT%/}"
echo "Probing ${BASE}"

curl -fsS --max-time 15 "${BASE}/health" >/dev/null
echo "OK /health"

curl -fsS --max-time 15 "${BASE}/ready" >/dev/null
echo "OK /ready"

echo "Edge probe passed (web /* routes; probes excluded from RED SLI per ADR-008 amendment)."
