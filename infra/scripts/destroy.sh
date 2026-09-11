#!/usr/bin/env bash
# One-command teardown of the dev environment. Required for G5's
# destroy/rebuild proof. Does NOT touch infra/bootstrap — the state bucket
# must outlive the environment it tracks.
set -euo pipefail
cd "$(dirname "$0")/../envs/dev"
terraform init -input=false
terraform destroy "$@"
