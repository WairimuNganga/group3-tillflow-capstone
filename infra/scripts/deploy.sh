#!/usr/bin/env bash
# One-command deploy of the dev environment.
#   ./infra/scripts/deploy.sh              # plan only
#   ./infra/scripts/deploy.sh --apply      # plan then apply
set -euo pipefail
cd "$(dirname "$0")/../envs/dev"

terraform init -input=false
terraform fmt -check -recursive ../..
terraform validate
terraform test
terraform plan -input=false -out=tfplan

terraform show -json tfplan > plan.json
../../scripts/audit-naming-tags.sh plan.json

if [ "${1:-}" = "--apply" ]; then
  terraform apply -input=false tfplan
fi
