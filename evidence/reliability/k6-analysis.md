# k6 capacity analysis (G3)

**Date:** _fill after run_  
**API:** `$API_ENDPOINT` (dev API Gateway `/v1`)  
**Load profile:** edge `/health` + `/ready` only (RED counters excluded per ADR-008).

## Results summary

| Script | Duration | Max VUs | http_req_failed | p(95) latency | checks pass |
|--------|----------|---------|-----------------|---------------|-------------|
| smoke.js | 30s | 2 | | | |
| baseline.js | 14m | 20 | | | |
| spike.js | 40s | 30 | | | |
| soak.js | 18m | 10 | | | |

## Highest sustained RPS where thresholds held

- **RPS:** _from k6 `http_reqs` rate at highest passing stage_
- **Bottleneck:** _API Gateway throttle / ALB / ECS CPU / RDS — cite CloudWatch or AMP if available_
- **Headroom:** _steps before p95 > 500ms or failed > 1%_
- **Cache:** _N/A for probe-only; note Redis if business routes added later_

## Artifacts

- JSON: `evidence/reliability/k6-soak.json` (and others as run)

## Commands

See [how-to-reproduce.md](./how-to-reproduce.md).
