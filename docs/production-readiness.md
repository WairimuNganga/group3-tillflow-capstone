# Production Readiness — DRI: Lwam

> Checklist: health/ready endpoints, sidecar boot, alarms, dashboards, backups, scans clean, rollback proven, cost estimate, cleanup plan.

## Current status

- Health/ready: public `/health` and `/ready` smoke tests pass through API Gateway → ALB → ECS.
- Sidecars: app containers, ADOT sidecars, and Service Connect sidecars are healthy in ECS evidence.
- Delivery: AWS CodePipeline builds/scans/pushes images, runs POS migrations, deploys ECS, and runs smoke.
- Rollback: Delivery rollback evidence is recorded in `evidence/delivery/rollback-log.md`.
- Observability: AMP, Grafana, ADOT remote write, CloudWatch Synthetics, and starter alarms are live.
- Platform evidence: see `evidence/platform/README.md`.
- Reliability evidence: see `evidence/reliability/reliability-and-operations.md`.

## Remaining before final gate

- G5 destroy/rebuild log.
- Drill 5 restore with measured RPO/RTO.
- Drill 3 alert/fire/recovery evidence.
- Grafana Slack contact point test evidence.
- X-Ray trace capture for sale → payment → callback.
- Final cost/cleanup note after destroy/rebuild rehearsal.
