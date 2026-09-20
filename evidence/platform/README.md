# Evidence — Platform

**DRI: Lwam** · cross-reviews Delivery

Platform evidence uses command output first; screenshots are optional support.

## Checklist

- [x] G2 database foundation evidence: RDS, proxy, bootstrap, secret shape, pipeline, ECS health.
- [x] Reproduction commands: [how-to-reproduce.md](./how-to-reproduce.md).
- [x] External probe Terraform: CloudWatch Synthetics `/health` + `/ready` canary.
- [x] Starter alarms Terraform: DLQ depth, canary success, ECS CPU, RDS CPU/connections.
- [ ] Apply evidence for latest canary/alarm change: `terraform-plan-*`, `terraform-apply-*`, naming/tag audit.
- [ ] Runtime canary proof: `synthetics-describe-*` and `synthetics-runs-*`.
- [ ] Runtime alarm proof: `cloudwatch-alarms-*`.
- [ ] G5 destroy/rebuild log.
- [ ] Drill 5 restore with measured RPO/RTO.

Gate-specific platform evidence:

- [G2 deliverables checklist](./G2-deliverables.md)
- [G2 handover](./G2-handover.md)
- [How to reproduce current platform evidence](./how-to-reproduce.md)
