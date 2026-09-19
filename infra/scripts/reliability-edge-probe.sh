#!/usr/bin/env bash
# Synthetic availability probe (B3) — public edge only, ADR-008 probe paths excluded from SLI.
set -euo pipefail

REGION="${AWS_REGION:-us-west-1}"
NAME_PREFIX="${NAME_PREFIX:-devops-g3}"

if [[ -z "${API_ENDPOINT:-}" ]]; then
  API_ENDPOINT="$(aws apigatewayv2 get-apis --region "$REGION" \
    --query "Items[?Name=='${NAME_PREFIX}-api'].ApiEndpoint | [0]" --output text 2>/dev/null || true)"
fi

if [[ -z "${API_ENDPOINT}" || "${API_ENDPOINT}" == "None" ]]; then
  echo "Set API_ENDPOINT or ensure ${NAME_PREFIX}-api exists in $REGION" >&2
  exit 1
fi

BASE="${API_ENDPOINT%/}"
echo "Probing ${BASE}"

curl -fsS --max-time 15 "${BASE}/health" >/dev/null
echo "OK /health"

curl -fsS --max-time 15 "${BASE}/ready" >/dev/null
echo "OK /ready"

echo "Edge probe passed (web /* routes; probes excluded from RED SLI per ADR-008 amendment)."
