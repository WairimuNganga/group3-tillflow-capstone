# Production Readiness — DRI: Lwam

> Checklist aligned with ALL-GATES review (G0–G5). Evidence paths are the proof.  
> **Review snapshot:** written against `e878e32` (21 Sep 2026). Gap closure and PR index: [all-gates-review-follow-up.md](all-gates-review-follow-up.md) (includes [#68](https://github.com/WairimuNganga/group3-tillflow-capstone/pull/68) drill + trace artifacts).

## G0–G2 — PASS

Ownership, ADRs, platform live, product e2e: `evidence/product/e2e-flow-output.txt` and `evidence/reliability/drill-1-2-timed-20260922.log` (**41 passed, 0 failed**).

Local reproduce: `services/pos/local/run-e2e.sh` (see `services/pos/local/README.md`).

## G3 — Operate

| Requirement | Status | Proof / action |
|-------------|--------|----------------|
| Synthetics canary | Done | `evidence/platform/synthetics-*-20260920.json`, `*-20260922.json` |
| k6 envelope | Done | `evidence/reliability/k6-analysis.md`, `k6-smoke-20260922.log` |
| Grafana + dashboards | Done | `evidence/reliability/reliability-and-operations.md` §B2 |
| Slack contact point | Done | `evidence/reliability/phase-f/screenshots/slack-grafana-testalert-20260922.png` |
| **Alert fire → recovery** | Done (ops) | Drill 3: `drill-3-alarm-firing-20260922.json` → `drill-3-alarm-ok-20260922.json` (DLQ depth ALARM→OK, ~10 min). Grafana **TestAlert** proves Slack delivery; rule-level Grafana fire optional when AMP has business traffic. |
| **X-Ray sale→payment→callback** | Done | `evidence/reliability/phase-f/traces/sale-payment-callback-20260921.md` + JSON |
| **X-Ray commission / B2C path** | Done (contract) | `phase-f/traces/commission-payout-via-payments-20260922.md` + e2e §5; commission service spans when worker runs in dev (see doc) |
| Edge probe | Done | `evidence/reliability/edge-probe-20260922.log` |

## G4 — Recover

| Drill | Status | Proof / action |
|-------|--------|----------------|
| 4 Rollback | Done | `evidence/delivery/rollback-log.md` |
| 3 DLQ / platform | Done | `evidence/reliability/drill-3-*-20260922.*`, `drill-3-platform-failure-20260922.md` |
| **1 Timeout → reconcile (timed)** | Done | `evidence/reliability/drill-1-2-timed-20260922.log` §4 (local Postgres + fake M-Pesa, timed flow) |
| **2 Callback replay + trace** | Done | Local duplicate: same log §3; deployed edge + X-Ray: `drill-2-deployed-callback-20260922.json`, `drill-2-deployed-xray-traces-20260922.json` |
| **5 RDS restore RPO/RTO** | Done | `evidence/platform/restore-drill-20260922.json` (RTO ~2.8m, temp instance deleted) |

## G5 — Release

| Requirement | Status | Proof / action |
|-------------|--------|----------------|
| Destroy/rebuild | Done | `evidence/platform/g5-*`, `rebuild-20260920.log` |
| README one-command | Done | root `README.md` |
| **Live 6-min defence** | Open | Per member; not in repo |

## Commands (current dev API)

```bash
export AWS_PROFILE=group3 AWS_REGION=us-west-1
export API_ENDPOINT=https://k8ve9ik8zl.execute-api.us-west-1.amazonaws.com/v1
curl -sS -o /dev/null -w '%{http_code}\n' "$API_ENDPOINT/health"
aws sso login --profile group3   # when token expires
```
