# Reliability — how to reproduce

Exact commands for G3/G4 evidence. Screenshots must pair with these steps.

## Prerequisites

```bash
aws login
export AWS_REGION=us-west-1
export AMP_WORKSPACE_ID=ws-40261a89-bf51-45ee-a25b-e5fdfa21b69d
export API_ENDPOINT="$(terraform -chdir=infra/envs/dev output -raw api_endpoint)"
pip install boto3   # AMP query script
```

## Edge probe (Phase C / B3)

```bash
bash infra/scripts/reliability-edge-probe.sh
```

## AMP validation (Phase B1)

```bash
bash infra/scripts/b1-amp-validate.sh
python3 infra/scripts/amp_promql_query.py "$AMP_WORKSPACE_ID" 'count({__name__=~".+"})'
```

## k6 (Phase B3 / D)

```bash
k6 run -e API_ENDPOINT="$API_ENDPOINT" reliability/k6/smoke.js
# Or wrapper (logs under evidence/reliability/):
bash infra/scripts/k6-phase-d.sh baseline   # ~14m
bash infra/scripts/k6-phase-d.sh soak       # ~18m
k6 run -e API_ENDPOINT="$API_ENDPOINT" reliability/k6/spike.js
```

## OTLP RED → AMP (B1 follow-up / dashboards)

```bash
bash infra/scripts/otlp-red-amp-verify.sh
# Grafana Explore: sum(rate(payments_requests_total[5m]))
```

## Phase F (dashboards + traces)

See [phase-f/README.md](./phase-f/README.md). Dashboard JSON copies live under `phase-f/dashboards/`.

Analysis template: [k6-analysis.md](./k6-analysis.md).

## B2 + B3 in parallel (same session)

**Terminal A — B3 load (sequential: smoke first, then long runs):**

```bash
cd ~/capstone/group3-tillflow-capstone
export AWS_REGION=us-west-1
export API_ENDPOINT="$(terraform -chdir=infra/envs/dev output -raw api_endpoint)"
bash infra/scripts/reliability-edge-probe.sh
k6 run -e API_ENDPOINT="$API_ENDPOINT" reliability/k6/smoke.js | tee evidence/reliability/k6-smoke.log
# Optional overnight / off-hours:
# k6 run -e API_ENDPOINT="$API_ENDPOINT" reliability/k6/baseline.js | tee evidence/reliability/k6-baseline.log
# k6 run -e API_ENDPOINT="$API_ENDPOINT" --out json=evidence/reliability/k6-soak.json reliability/k6/soak.js
```

**Terminal B — B2 Grafana (after Terraform apply + pipeline `build-grafana`):**

```bash
cd ~/capstone/group3-tillflow-capstone
terraform -chdir=infra/envs/dev output grafana_url amp_prometheus_endpoint grafana_admin_secret_arn
# Set admin password (once): aws secretsmanager put-secret-value --secret-id <grafana_admin_secret_arn> --secret-string '…'
# Open grafana_url → login admin → Connections → AMP should already exist (uid AMP)
# Dashboards → TillFlow folder (provisioned from image) or re-import JSON from infra/grafana/dashboards/
# Panels may show no RED until OTLP app metrics land in AMP; ecs_task_* still validates datasource.
```

Do **not** run `spike.js` at the same time as baseline/soak (T1.3 — notify team, run alone).

## External synthetics (Phase C — Terraform TODO)

Wire CloudWatch Synthetics canary to `$API_ENDPOINT/health` (1-minute schedule). Until TF lands, edge probe script is the manual stand-in.

## Grafana (Phase B)

Terraform module `grafana-service` + ALB `/grafana/*`. See [infra/grafana/README.md](../../infra/grafana/README.md).

## Grafana alerts (Phase E)

After `grafana_image_tag` **11.4.0-tillflow2** (or newer) is in ECR and ECS:

```bash
terraform -chdir=infra/envs/dev output grafana_url
# Grafana UI → Alerting → Contact points → slack-tillflow → Test
# Alerting → Alert rules → folder TillFlow Alerts (3 rules)
aws secretsmanager get-secret-value --secret-id devops-g3/slack-webhook \
  --query 'length(SecretString)' --output text   # must be > 0
```

Record results in [reliability-and-operations.md](./reliability-and-operations.md) §Phase E.

## Drill 3 (Phase G)

Document timed steps here after execution (platform failure → alert → runbook → recovery).
