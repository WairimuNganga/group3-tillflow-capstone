#!/usr/bin/env bash
# One-command deploy of the dev environment.
#   ./infra/scripts/deploy.sh              # plan only
#   ./infra/scripts/deploy.sh --apply      # plan then apply
set -euo pipefail
cd "$(dirname "$0")/../envs/dev"

resolve_image_versions() {
  local tags=""
  local digests=""
  local svc
  local sha
  local digest

  for svc in web pos payments commission; do
    sha="$(aws ssm get-parameter \
      --name "/devops-g3/${svc}/image-tag" \
      --query 'Parameter.Value' \
      --output text 2>/dev/null || echo "REPLACE_ME")"

    digest="$(aws ssm get-parameter \
      --name "/devops-g3/${svc}/image-digest" \
      --query 'Parameter.Value' \
      --output text 2>/dev/null || true)"

    echo "image ${svc}: tag=${sha} digest=${digest:-unset}"
    tags="${tags}${svc}=\"${sha}\","
    if [ -n "${digest}" ] && [ "${digest}" != "UNSET" ]; then
      digests="${digests}${svc}=\"${digest}\","
    fi
  done

  export TF_VAR_image_tags="{${tags%,}}"
  export TF_VAR_image_digests="{${digests%,}}"
}

terraform init -input=false
terraform fmt -check -recursive ../..
terraform validate
terraform test
resolve_image_versions
terraform plan -input=false -out=tfplan

terraform show -json tfplan > plan.json
../../scripts/audit-naming-tags.sh plan.json

if [ "${1:-}" = "--apply" ]; then
  terraform apply -input=false tfplan
fi
