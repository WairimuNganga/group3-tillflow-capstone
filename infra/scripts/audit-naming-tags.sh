#!/usr/bin/env bash
# G1 naming + tag audit.
#
# The brief requires every nameable resource prefixed devops-g<N> and tagged
# group, owner, environment, service, managed-by=terraform, capstone=tillflow.
# This checks the *plan*, not the console, so it runs on a PR with no
# credentials and its output is reproducible evidence.
#
#   ./infra/scripts/audit-naming-tags.sh path/to/plan.json
#
# Produce the input with:
#   terraform -chdir=infra/envs/dev plan -out=tfplan
#   terraform -chdir=infra/envs/dev show -json tfplan > plan.json

set -euo pipefail

PLAN_JSON="${1:?usage: $0 <plan.json>}"
PREFIX="${NAME_PREFIX:-devops-g3}"
REQUIRED_TAGS=(group owner environment service managed-by capstone)

command -v jq >/dev/null || { echo "jq is required"; exit 2; }

fail=0
checked=0

# Resource types that carry a user-chosen name AND support tags. Types that
# AWS names for you (route table associations, SG rules, policy attachments)
# are deliberately excluded — asserting a prefix on them would be noise.
NAMED_TYPES='["aws_vpc","aws_subnet","aws_security_group","aws_lb","aws_lb_target_group","aws_ecs_cluster","aws_ecs_service","aws_ecs_task_definition","aws_ecr_repository","aws_db_instance","aws_db_proxy","aws_elasticache_replication_group","aws_sqs_queue","aws_s3_bucket","aws_iam_role","aws_cloudwatch_log_group","aws_kms_alias","aws_dynamodb_table","aws_apigatewayv2_api","aws_apigatewayv2_vpc_link","aws_scheduler_schedule","aws_nat_gateway"]'

echo "== naming: every resource starts with '${PREFIX}' =="
while IFS=$'\t' read -r addr name; do
  [ -z "${name}" ] && continue
  checked=$((checked + 1))
  # Log groups and ECR repos legitimately start with '/' or use the slash form.
  normalized="${name#/}"
  if [[ "${normalized}" != "${PREFIX}"* ]]; then
    echo "  FAIL ${addr}: name '${name}' is not prefixed '${PREFIX}'"
    fail=1
  fi
done < <(
  jq -r --argjson types "${NAMED_TYPES}" '
    .planned_values.root_module
    | [recurse(.child_modules[]?) | .resources[]?]
    | map(select(.type as $t | $types | index($t)))
    | .[]
    | [.address, (.values.name // .values.bucket // .values.identifier // .values.replication_group_id // "")]
    | @tsv
  ' "${PLAN_JSON}"
)

echo "== tags: every taggable resource carries all ${#REQUIRED_TAGS[@]} required tags =="
while IFS=$'\t' read -r addr tagsjson; do
  [ "${tagsjson}" = "null" ] && continue
  for t in "${REQUIRED_TAGS[@]}"; do
    if ! echo "${tagsjson}" | jq -e --arg t "${t}" 'has($t)' >/dev/null; then
      echo "  FAIL ${addr}: missing required tag '${t}'"
      fail=1
    fi
  done
  # These two are fixed values, not free text.
  if [ "$(echo "${tagsjson}" | jq -r '.["managed-by"] // ""')" != "terraform" ]; then
    echo "  FAIL ${addr}: managed-by must be 'terraform'"
    fail=1
  fi
  if [ "$(echo "${tagsjson}" | jq -r '.capstone // ""')" != "tillflow" ]; then
    echo "  FAIL ${addr}: capstone must be 'tillflow'"
    fail=1
  fi
done < <(
  jq -r '
    .planned_values.root_module
    | [recurse(.child_modules[]?) | .resources[]?]
    | map(select(.values.tags_all != null))
    | .[]
    | [.address, (.values.tags_all | tostring)]
    | @tsv
  ' "${PLAN_JSON}"
)

echo "== forbidden: no 'latest' image tag anywhere =="
if jq -e '[recurse] | map(select(type == "string" and test(":latest\"?$"))) | length > 0' "${PLAN_JSON}" >/dev/null 2>&1; then
  echo "  FAIL: a ':latest' image reference appears in the plan (ADR-009)"
  fail=1
fi

echo
if [ "${fail}" -eq 0 ]; then
  echo "PASS — ${checked} named resources checked, all tags present."
else
  echo "FAIL — see above."
fi
exit "${fail}"
