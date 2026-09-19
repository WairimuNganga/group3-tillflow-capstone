# Grafana (B2)

**DRI:** Minage (dashboards/alerts) · **Platform:** Lwam (Grafana ECS task, ALB, auth — ADR-001)

Amazon Managed Grafana is **not** available in `us-west-1`. We self-host Grafana on ECS and use **AMP** as the Prometheus data source.

## Dashboard-as-code

| Path | Purpose |
|------|---------|
| [dashboards/payments-service-overview.json](./dashboards/payments-service-overview.json) | RED + error ratio for `payments` |
| [dashboards/web-service-overview.json](./dashboards/web-service-overview.json) | RED for `web` |
| [provisioning/datasources/amp.yaml.example](./provisioning/datasources/amp.yaml.example) | Wire AMP after deploy |

Import JSON in Grafana **or** mount under `/etc/grafana/provisioning/dashboards` when the ECS service exists.

## AMP datasource (after B0)

From dev Terraform:

```bash
terraform -chdir=infra/envs/dev output amp_prometheus_endpoint
```

In Grafana: Prometheus plugin, **SigV4 auth**, region `us-west-1`, URL = that endpoint (no `/api/v1/remote_write` suffix).

## Local preview (optional)

Use AWS SSO credentials and point Grafana at AMP the same way; do not commit admin passwords or webhook URLs.

## Alerts → Slack

Alert rules reference panels here; webhook lives in Secrets Manager `devops-g3/slack-webhook` (B0). See [docs/runbook.md](../../docs/runbook.md#observability-alerts).
