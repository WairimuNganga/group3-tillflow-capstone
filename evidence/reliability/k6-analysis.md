# k6 capacity analysis (G3)

**Date:** 2026-09-19 (smoke); **2026-09-20** baseline + soak ✓  
**API:** `https://w6m0ja1aic.execute-api.us-west-1.amazonaws.com/v1` (dev API Gateway)  
**Load profile:** edge `/health` + `/ready` only (RED counters excluded per ADR-008).

## Results summary

| Script | Duration | Max VUs | http_req_failed | p(95) latency | checks pass |
|--------|----------|---------|-----------------|---------------|-------------|
| smoke.js | 30s | 2 | 0.00% (0/78) | 287.6ms | 100% (78/78) |
| baseline.js | 14m | 20 | 0.00% (0/15420) | 275.0ms | 100% (15420/15420) |
| spike.js | 40s | 30 | 0.00% (0/1820) | 293.32ms | 100% (1820/1820) |
| soak.js | 18m | 10 | 0.00% (0/8782) | 302.82ms | 100% (8782/8782) |

## Highest sustained RPS where thresholds held

- **RPS (smoke):** ~2.48 req/s (2 VUs, 1s sleep); 78 HTTP requests in 30s
- **RPS (baseline):** ~18.35 req/s sustained (7710 iterations × 2 requests, 14m); thresholds held at up to **20 VUs**
- **RPS (soak):** ~8.12 req/s sustained (4391 iterations × 2 requests, 18m at up to **10 VUs**)
- **Bottleneck:** Not hit on edge probes — soak p95 **302.82ms** remained below the 500ms threshold with no failed requests
- **Headroom:** Baseline ramp 5→10→20 VUs over 14m and the 30-VU spike both completed with zero errors; the spike sustained approximately **45.39 req/s** with p95 **293.32ms**
- **Cache:** _N/A for probe-only; note Redis if business routes added later_

## Artifacts

- Log: `evidence/reliability/k6-smoke.log` (2026-09-19)
- Log: `evidence/reliability/k6-baseline.log` (2026-09-20)
- Log: `evidence/reliability/k6-spike-20260920.log` (2026-09-20)
- Log / JSON: `k6-soak.log`, `k6-soak.json` (2026-09-20, after soak completes)

## Commands

```bash
export AWS_REGION=us-west-1
export API_ENDPOINT="$(terraform -chdir=infra/envs/dev output -raw api_endpoint)"
k6 run -e API_ENDPOINT="$API_ENDPOINT" reliability/k6/smoke.js | tee evidence/reliability/k6-smoke.log
```

Copy **http_req_failed**, **http_req_duration p(95)**, and **checks** from the k6 end summary into the table above. See [how-to-reproduce.md](./how-to-reproduce.md) for baseline/soak/spike.
