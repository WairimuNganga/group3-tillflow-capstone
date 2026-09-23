# Phase F — ADR-008 proof (dashboards + traces)

**DRI:** Minage · **Graders:** pair screenshots/IDs with commands in [how-to-reproduce.md](../how-to-reproduce.md).

## Dashboards

| Artifact | Source |
|----------|--------|
| [payments-service-overview.json](./dashboards/payments-service-overview.json) | Copy of `infra/grafana/dashboards/payments-service-overview.json` (dashboard-as-code) |
| [web-service-overview.json](./dashboards/web-service-overview.json) | Copy of `infra/grafana/dashboards/web-service-overview.json` |
| [tillflow-slo-overview.json](./dashboards/tillflow-slo-overview.json) | SLO uptime, burn-rate, latency, and money-safety dashboard-as-code |

**Live proof (add after capture):**

- [x] Grafana screenshots: TillFlow SLO and payments dashboards (`screenshots/*-20260920.png`); sparse business panels honestly show `No data`
- [x] Explore screenshots: AMP visible-series query and payments RED metric discovery (`screenshots/amp-query-20260920.png`, `screenshots/payments-red-query-20260920.png`)

Optional: Grafana **Share → Export → Save to file** and replace the JSON here if the live board diverges from repo.

## Traces (A5 / Phase F)

Captured 2026-09-21 18:02 UTC / 21:02 EAT. Full analysis, timeline and
reproduction: **[traces/sale-payment-callback-20260921.md](./traces/sale-payment-callback-20260921.md)**.

One transaction produces **three traces, not one** — Safaricom initiates the
callback as a new inbound request with no upstream context, so it cannot be
stitched to the STK trace. They correlate by sale ID
`2c1cbb8b-4389-421a-b60c-e31dd58cd89b`.

| Date | Trace ID | Services | Flow | Duration |
|------|----------|----------|------|----------|
| 2026-09-21 | `1-f9c854e2-60292f314acf2756b35d6933` | payments | STK push to Daraja (202) | 2.946s |
| 2026-09-21 | `1-36eca49c-b1002c99118ffde2f7227f4e` | web, pos | Web → POS sale read (200) | 0.059s |
| 2026-09-21 | `1-bafcca63-80239dc21ef6b719ac120203` | payments, pos | Callback → POS settlement (200) | 0.144s |

- [x] Raw trace JSON committed under `traces/` (summaries + one file per trace)
- [ ] X-Ray console service-map screenshot — optional; the JSON is the proof

**Commission → Payments (B2C):** Contract and layered proof (local e2e + architecture; commission ECS spans when worker runs in dev):

- [traces/commission-payout-via-payments-20260922.md](./traces/commission-payout-via-payments-20260922.md)
- AWS B2C trace/log supplement: `traces/xray-b2c-summaries-20260923.json`, `traces/xray-b2c-trace-20260923.json`, and `traces/b2c-commission-payments-log-20260923.txt`.

**Drills 1–2 deployed supplement:** `../drill-1-2-deployed-aws-20260923.md` records deployed POS → Payments logs and X-Ray trace `1-94dbe6a4-965419f4b305798c78322278`, supplementing the timed local money-safety proof.

**Known gap:** POS → Payments does not propagate trace context, so STK
initiation cannot be followed from the browser in one trace. Web → POS and
Payments → POS both propagate correctly. Diagnosis in the analysis document.

**Commands:**

```bash
export AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1
DATE=$(date -u +%Y%m%d); OUT=evidence/reliability/phase-f/traces
: "${OUT:?}" "${DATE:?}"

# after a sale → STK → callback in dev, wait ~60s:
aws xray get-trace-summaries \
  --start-time $(date -u -v-30M +%s) --end-time $(date -u +%s) \
  --output json > "$OUT/xray-summaries-${DATE}.json"

jq -r '.TraceSummaries[] | [.Id,.Duration,.HasError,.HasFault] | @tsv' \
  "$OUT/xray-summaries-${DATE}.json"
```

Do **not** filter on `service(id(name: "payments"))` — it hides the Web → POS
trace and makes a working capture look empty. Note `date -u -v-30M` is BSD/macOS;
on Linux use `date -u -d '30 min ago'`.

Tracing produced **zero** traces until PR #66: the task role granted every
`xray:*` action but scoped the statement to the AMP workspace ARN (X-Ray
requires `"*"`), and behind that, three services with no internet egress had no
X-Ray or AMP VPC endpoint. Both are now guarded by assertions in
`infra/envs/dev/tests/architecture.tftest.hcl`.
