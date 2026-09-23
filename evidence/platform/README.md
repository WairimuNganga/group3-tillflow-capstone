# Evidence — Platform

**DRI: Lwam** · cross-reviews Delivery

Platform evidence uses command output first; screenshots are optional support.

## Checklist

- [x] G2 database foundation evidence: RDS, proxy, bootstrap, secret shape, pipeline, ECS health.
- [x] Reproduction commands: [how-to-reproduce.md](./how-to-reproduce.md).
- [x] External probe Terraform: CloudWatch Synthetics `/health` + `/ready` canary.
- [x] Starter alarms Terraform: DLQ depth, canary success, ECS CPU, RDS CPU/connections.
- [x] Apply evidence for latest canary/alarm change: GitHub Terraform apply passed; runtime evidence below confirms the resources are live.
- [x] Runtime canary proof: [`synthetics-describe-20260920.json`](./synthetics-describe-20260920.json) and [`synthetics-runs-20260920.json`](./synthetics-runs-20260920.json).
- [x] Runtime alarm proof: [`cloudwatch-alarms-20260920.json`](./cloudwatch-alarms-20260920.json).
- [x] Naming/tag audit proof: [`naming-tag-audit-20260923.log`](./naming-tag-audit-20260923.log).
- [x] DB bootstrap status and credential-free schema/role/RLS audit:
  [`db-bootstrap-status-20260923.json`](./db-bootstrap-status-20260923.json),
  [`db-roles-rls-20260923.log`](./db-roles-rls-20260923.log).
- [x] G5 destroy/rebuild log and post-rebuild verification.
- [x] Drill 5 restore with measured RPO/RTO — `restore-drill-20260922.json`

## Latest runtime evidence — 2026-09-20

- CloudWatch Synthetics canary `devops-g3-edge-health` is `RUNNING`.
- Canary runtime is `syn-nodejs-puppeteer-17.0`.
- Last five canary runs captured in evidence are `PASSED`.
- CloudWatch alarm evidence includes:
  - `devops-g3-edge-health-canary`
  - `devops-g3-web-ecs-cpu-high`
  - `devops-g3-pos-ecs-cpu-high`
  - `devops-g3-payments-ecs-cpu-high`
  - `devops-g3-commission-ecs-cpu-high`
  - `devops-g3-rds-cpu-high`
  - `devops-g3-rds-connections-high`
  - `devops-g3-payout-dlq-depth`
  - `devops-g3-reconciliation-dlq-depth`

Gate-specific platform evidence:

- [G2 deliverables checklist](./G2-deliverables.md)
- [G2 handover](./G2-handover.md)
- [How to reproduce current platform evidence](./how-to-reproduce.md)

## G5 destroy/rebuild evidence — 2026-09-20

- Destroy log:
  - [`destroy-20260920-142510.log`](./destroy-20260920-142510.log)
  - [`destroy-resume-20260920.log`](./destroy-resume-20260920.log)
- Empty state proof after destroy: [`g5-state-after-destroy-20260920.txt`](./g5-state-after-destroy-20260920.txt).
- Rebuild log: [`rebuild-20260920.log`](./rebuild-20260920.log).
- DB bootstrap proof: [`g5-db-bootstrap-20260920.json`](./g5-db-bootstrap-20260920.json).
- CodePipeline proof: [`g5-pipeline-after-rebuild-20260920.json`](./g5-pipeline-after-rebuild-20260920.json).
- ECS service proof: [`g5-services-after-rebuild-20260920.json`](./g5-services-after-rebuild-20260920.json).
- ECS task/container proof: [`g5-tasks-after-rebuild-20260920.json`](./g5-tasks-after-rebuild-20260920.json).
- Smoke proof: [`g5-smoke-after-rebuild-20260920.txt`](./g5-smoke-after-rebuild-20260920.txt).
- Synthetics proof:
  - [`g5-synthetics-after-rebuild-20260920.json`](./g5-synthetics-after-rebuild-20260920.json)
  - [`g5-synthetics-runs-after-rebuild-20260920.json`](./g5-synthetics-runs-after-rebuild-20260920.json)

Summary:

- Terraform rebuild completed: `Apply complete! Resources: 244 added, 8 changed, 0 destroyed.`
- Pipeline stages `Source`, `BuildScanPush`, `MigrateDb`, `DeployEcs`, and `Smoke` all finished `Succeeded`.
- ECS services after rebuild: web `2/2`, POS `2/2`, payments `2/2`, commission `1/1`, Grafana `1/1`; all rollouts `COMPLETED`.
- Smoke after rebuild returned HTTP `200` for `/health` and `/ready`.
- Last five Synthetics canary runs after rebuild are `PASSED`.

## Platform audit evidence — 2026-09-23

- Naming/tag audit passed: `104` named resources checked and all required tags present.
- DB bootstrap rerun succeeded: [`db-bootstrap-status-20260923.json`](./db-bootstrap-status-20260923.json).
- Credential-free DB audit proof: [`db-roles-rls-20260923.log`](./db-roles-rls-20260923.log).
  - `web`, `pos`, `payments`, and `commission` schemas are owned by their owner roles.
  - Runtime roles can log in, are not superusers, and have `rolbypassrls = false`.
  - Runtime roles have schema `USAGE` but not schema `CREATE`.
  - POS tenant tables have RLS enabled and forced with `tenant_isolation` policies.
