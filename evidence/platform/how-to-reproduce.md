# Platform evidence — how to reproduce

**DRI:** Lwam · Cross-review: Delivery

## Prerequisites

```bash
export AWS_REGION=us-west-1
export AWS_PROFILE=tillflow-g3-lwam   # or your SSO profile
cd ~/capstone/group3-tillflow-capstone
```

## Terraform plan + naming/tag audit (G1)

```bash
./infra/scripts/deploy.sh
cp infra/envs/dev/plan.json "evidence/platform/terraform-plan-$(date -u +%Y%m%d).json"
terraform -chdir=infra/envs/dev show -no-color tfplan | tee "evidence/platform/terraform-plan-$(date -u +%Y%m%d).txt"
../../infra/scripts/audit-naming-tags.sh infra/envs/dev/plan.json | tee "evidence/platform/naming-tag-audit-$(date -u +%Y%m%d).log"
```

Apply when intentional:

```bash
./infra/scripts/deploy.sh --apply
# Capture tail of apply output:
tee "evidence/platform/terraform-apply-$(date -u +%Y%m%d).log"
```

## CloudWatch Synthetics canary (G3 external probe)

After apply:

```bash
CANARY="$(terraform -chdir=infra/envs/dev output -raw synthetics_canary_name)"
terraform -chdir=infra/envs/dev output -json synthetics_probe_urls

aws synthetics describe-canaries --names "$CANARY" --region "$AWS_REGION" \
  | tee "evidence/platform/synthetics-describe-$(date -u +%Y%m%d).json"

aws synthetics get-canary-runs --name "$CANARY" --region "$AWS_REGION" --max-results 5 \
  | tee "evidence/platform/synthetics-runs-$(date -u +%Y%m%d).json"
```

## CloudWatch alarms (DLQ + canary)

```bash
terraform -chdir=infra/envs/dev output -json cloudwatch_alarm_names
aws cloudwatch describe-alarms --alarm-name-prefix devops-g3 --region "$AWS_REGION" \
  | tee "evidence/platform/cloudwatch-alarms-$(date -u +%Y%m%d).json"
```

## DB bootstrap (G2 platform foundation)

```bash
aws codebuild start-build --project-name devops-g3-db-bootstrap --region "$AWS_REGION"
# Then fetch build logs via console or:
BUILD_ID="$(aws codebuild list-builds-for-project --project-name devops-g3-db-bootstrap --sort-order DESCENDING --query 'ids[0]' --output text)"
aws codebuild batch-get-builds --ids "$BUILD_ID" --query 'builds[0].{status:buildStatus,phase:currentPhase}' \
  | tee "evidence/platform/db-bootstrap-status-$(date -u +%Y%m%d).json"
```

Schema/roles/RLS proof: run from controlled migration path only — **never paste DB passwords into evidence**. Use `\dn`, `\du`, and `\d+ pos.sales` output with secrets redacted.

## Destroy / rebuild (G5)

```bash
./infra/scripts/destroy.sh -auto-approve 2>&1 | tee "evidence/platform/destroy-$(date -u +%Y%m%d).log"
./infra/scripts/bootstrap.sh
./infra/scripts/deploy.sh --apply 2>&1 | tee "evidence/platform/rebuild-$(date -u +%Y%m%d).log"
terraform -chdir=infra/envs/dev output api_endpoint
```

## Restore drill (G4 — with Minage)

See [docs/lwam-minage-implementation-plan.md](../../docs/lwam-minage-implementation-plan.md) § Drill 5. Record timed steps in `evidence/platform/restore-drill-<date>.md`.
