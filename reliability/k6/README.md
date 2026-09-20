# k6 load tests (B3)

**DRI:** Minage · **ADR:** [ADR-008](../../docs/adr/ADR-008-telemetry-conventions.md), threat model T1.3

Synthetic MSISDNs and Daraja **sandbox** only — never real subscriber numbers in scripts or output.

## Prerequisites

- [k6](https://k6.io/docs/get-started/installation/) installed locally
- Dev API base URL (same as post-deploy smoke):

  ```bash
  export AWS_REGION=us-west-1
  export API_ENDPOINT="$(terraform -chdir=infra/envs/dev output -raw api_endpoint)"
  ```

## Smoke (low rate)

```bash
k6 run -e API_ENDPOINT="$API_ENDPOINT" reliability/k6/smoke.js
```

## Baseline (stepped ramp ~14m)

```bash
k6 run -e API_ENDPOINT="$API_ENDPOINT" reliability/k6/baseline.js
```

## Soak (≥18m at moderate VUs)

```bash
k6 run -e API_ENDPOINT="$API_ENDPOINT" --summary-export evidence/reliability/k6-soak.json reliability/k6/soak.js
```

## Spike (brief burst — run manually, not in CI by default)

```bash
k6 run -e API_ENDPOINT="$API_ENDPOINT" reliability/k6/spike.js
```

Record results in [evidence/reliability/k6-analysis.md](../../evidence/reliability/k6-analysis.md).

Metrics from k6 must not include raw MSISDNs or secrets in labels (T8.1).
