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

| Date | Trace ID | Service | Flow | Capture |
|------|----------|---------|------|---------|
| | | | sale → payment → callback | X-Ray console screenshot or `aws xray get-trace-summaries` |

**Commands (fill trace ID in table):**

```bash
export AWS_REGION=us-west-1
# After a sale/STK path in dev:
aws xray get-trace-summaries --start-time $(date -u -d '15 min ago' +%s) --end-time $(date -u +%s) \
  --filter-expression 'service(id(name: "payments"))' --query 'TraceSummaries[0].Id' --output text
```

Save screenshot under `evidence/reliability/phase-f/traces/` (create when you have a capture).
