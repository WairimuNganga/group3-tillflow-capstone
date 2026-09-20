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
- [ ] G5 destroy/rebuild log.
- [ ] Drill 5 restore with measured RPO/RTO.

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
