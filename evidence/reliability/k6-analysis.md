# k6 capacity analysis (G3)

**Date:** 2026-09-19  
**API:** `https://w6m0ja1aic.execute-api.us-west-1.amazonaws.com/v1` (dev API Gateway)  
**Load profile:** edge `/health` + `/ready` only (RED counters excluded per ADR-008).

## Results summary

| Script | Duration | Max VUs | http_req_failed | p(95) latency | checks pass |
|--------|----------|---------|-----------------|---------------|-------------|
| smoke.js | 30s | 2 | 0.00% (0/78) | 287.6ms | 100% (78/78) |
| baseline.js | 14m | 20 | | | |
| spike.js | 40s | 30 | | | |
| soak.js | 18m | 10 | | | |

## Highest sustained RPS where thresholds held

- **RPS:** ~2.48 req/s sustained (smoke, 2 VUs, probe loop with 1s sleep); 78 HTTP requests in 30s
- **Bottleneck:** _API Gateway throttle / ALB / ECS CPU / RDS — cite CloudWatch or AMP if available_
- **Headroom:** _steps before p95 > 500ms or failed > 1%_
- **Cache:** _N/A for probe-only; note Redis if business routes added later_

## Artifacts

- Log: `evidence/reliability/k6-smoke.log` (2026-09-19)
- JSON: `evidence/reliability/k6-soak.json` (when soak run)

## Commands

```bash
export AWS_REGION=us-west-1
export API_ENDPOINT="$(terraform -chdir=infra/envs/dev output -raw api_endpoint)"
k6 run -e API_ENDPOINT="$API_ENDPOINT" reliability/k6/smoke.js | tee evidence/reliability/k6-smoke.log
```

Copy **http_req_failed**, **http_req_duration p(95)**, and **checks** from the k6 end summary into the table above. See [how-to-reproduce.md](./how-to-reproduce.md) for baseline/soak/spike.
