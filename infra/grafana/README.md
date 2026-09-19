# Grafana (B2) — Option B on ECS

**DRI:** Minage (dashboards/alerts) · **Platform:** Lwam (Grafana ECS task, ALB, auth — ADR-001)

Amazon Managed Grafana is **not** available in `us-west-1`. We self-host Grafana on **ECS Fargate** behind the same internal ALB as the apps, at **`{api_endpoint}/grafana/`**.

## After Terraform apply (dev)

```bash
terraform -chdir=infra/envs/dev output grafana_url grafana_admin_secret_arn amp_prometheus_endpoint
```

1. **Admin password** (plain string, not JSON):

   ```bash
   aws secretsmanager put-secret-value \
     --secret-id "$(terraform -chdir=infra/envs/dev output -raw grafana_admin_secret_arn)" \
     --secret-string 'choose-a-strong-password'
   ```

2. **Grafana image** — run the delivery pipeline (or CodeBuild `devops-g3-grafana-build`) so `11.4.0-tillflow1` exists in ECR before the ECS service can stay healthy.

3. Open **`grafana_url`**, sign in as `admin`, confirm **Connections → Data sources → AMP** (SigV4, provisioned at task start).

## Dashboard-as-code

| Path | Purpose |
|------|---------|
| [dashboards/payments-service-overview.json](./dashboards/payments-service-overview.json) | RED + error ratio for `payments` |
| [dashboards/web-service-overview.json](./dashboards/web-service-overview.json) | RED for `web` |
| [provisioning/datasources/amp.yaml.example](./provisioning/datasources/amp.yaml.example) | Reference; live datasource is rendered in [docker-entrypoint.sh](./docker-entrypoint.sh) |

Dashboards are baked into the ECR image and loaded from `/var/lib/grafana/dashboards` (uid **AMP**).

## Alerts → Slack

Alert rules reference panels here; webhook lives in Secrets Manager `devops-g3/slack-webhook` (B0). The Grafana task role may read that secret for provisioned contact points. See [docs/runbook.md](../../docs/runbook.md#observability-alerts).

## Bump image tag

When changing `infra/grafana/` (Dockerfile, dashboards, entrypoint), bump `grafana_image_tag` in `infra/envs/dev/main.tf`, **terraform apply**, then **Release change** on the pipeline so CodeBuild pushes the new tag.
