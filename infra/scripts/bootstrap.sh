#!/usr/bin/env bash
# One-command bootstrap. Run ONCE per AWS account, before anything else.
# Creates the state bucket, lock table, shared CMK and the OIDC CI role.
set -euo pipefail
cd "$(dirname "$0")/../bootstrap"
terraform init
terraform apply "$@"
echo
echo "Put these into infra/envs/dev/backend.tf and terraform.tfvars:"
terraform output
