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

## k6 (Phase D)

```bash
k6 run -e API_ENDPOINT="$API_ENDPOINT" reliability/k6/smoke.js
k6 run -e API_ENDPOINT="$API_ENDPOINT" reliability/k6/baseline.js
k6 run -e API_ENDPOINT="$API_ENDPOINT" reliability/k6/spike.js
k6 run -e API_ENDPOINT="$API_ENDPOINT" --out json=evidence/reliability/k6-soak.json reliability/k6/soak.js
```

Analysis template: [k6-analysis.md](./k6-analysis.md).

## External synthetics (Phase C — Terraform TODO)

Wire CloudWatch Synthetics canary to `$API_ENDPOINT/health` (1-minute schedule). Until TF lands, edge probe script is the manual stand-in.

## Grafana (Phase B)

After Grafana ECS is live: import JSON from `infra/grafana/dashboards/`, AMP datasource per [infra/grafana/README.md](../../infra/grafana/README.md).

## Drill 3 (Phase G)

Document timed steps here after execution (platform failure → alert → runbook → recovery).
