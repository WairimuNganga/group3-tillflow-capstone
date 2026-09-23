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

2. **Grafana image** — run the delivery pipeline (or CodeBuild `devops-g3-grafana-build`) so the pinned `grafana_image_tag` in `infra/envs/dev/main.tf` exists in ECR before the ECS service can stay healthy.

3. Open **`grafana_url`** (must be `…/v1/grafana/` — not a URL with repeated `/grafana/` segments), sign in as `admin`, confirm **Connections → Data sources → AMP** (SigV4, provisioned at task start).

   Redirect loops were caused by API Gateway forwarding `/grafana/…` while `GF_SERVER_ROOT_URL` used `/v1/grafana/`. Terraform fixes that by rewriting Grafana routes to `/v1/grafana/…` at the edge (**terraform apply**, not CodePipeline).

## Dashboard-as-code

| Path | Purpose |
|------|---------|
| [dashboards/payments-service-overview.json](./dashboards/payments-service-overview.json) | RED + error ratio for `payments` |
| [dashboards/web-service-overview.json](./dashboards/web-service-overview.json) | RED for `web` |
| [provisioning/datasources/amp.yaml.example](./provisioning/datasources/amp.yaml.example) | Reference; live datasource is rendered in [docker-entrypoint.sh](./docker-entrypoint.sh) |

Dashboards are baked into the ECR image and loaded from `/var/lib/grafana/dashboards` (uid **AMP**).

## Phase E — Alerts → Slack

**Secret:** `devops-g3/slack-webhook` (plain-string incoming webhook URL, set in B0).

**Provisioned in the image** (after `11.4.0-tillflow2`+):

| File | Purpose |
|------|---------|
| [provisioning/alerting/rules.yaml](./provisioning/alerting/rules.yaml) | Runbook starters: PaymentsHigh5xxRate, PaymentsLatencyP95; EdgeProbeFailed inert in Grafana (CloudWatch canary alarm is edge SoT) |
| [provisioning/alerting/policies.yaml](./provisioning/alerting/policies.yaml) | Default route → `slack-tillflow` |
| [docker-entrypoint.sh](./docker-entrypoint.sh) | Writes `contact-points.yaml` from env `SLACK_WEBHOOK_URL` (injected by ECS from Secrets Manager) |

**Deploy:** bump `grafana_image_tag` → **terraform apply (dev)** → CodePipeline **Release change** (`build-grafana`) → ECS rolls to new task def (Terraform).

**Verify:**

1. **Alerting → Contact points → slack-tillflow → Test** (should post to Slack).
2. **Alerting → Alert rules → TillFlow Alerts** — three rules; RED rules may show **No data** until OTLP metrics exist.
3. Record test in [evidence/reliability/reliability-and-operations.md](../../evidence/reliability/reliability-and-operations.md) §Phase E.

See [docs/runbook.md](../../docs/runbook.md#observability-alerts).

## Bump image tag

When changing `infra/grafana/` (Dockerfile, dashboards, entrypoint), bump `grafana_image_tag` in `infra/envs/dev/main.tf`, **terraform apply**, then **Release change** on the pipeline so CodeBuild pushes the new tag.
