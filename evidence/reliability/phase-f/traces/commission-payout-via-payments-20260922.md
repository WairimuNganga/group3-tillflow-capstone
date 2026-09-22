# Commission payout path — B2C via Payments (2026-09-22)

**Gate:** G3 captured traces (commission / money path). **DRI:** Minage.

## What graders ask for

Scheduled close → commission → **Payments `/payments/b2c`** (never Daraja from commission). That contract is the money-critical hop.

## Proof (layered)

| Layer | Artifact | What it shows |
|-------|----------|----------------|
| **G2 local (timed)** | `evidence/reliability/drill-1-2-timed-20260922.log` §5 | 41/41 incl. B2C 202, idempotent replay, `completed` after `/payments/b2c/result` |
| **Product** | `evidence/product/e2e-flow-output.txt` | Same invariants on recorded run |
| **Architecture** | ADR + commission client | Commission has no Daraja credentials; B2C only through Payments |
| **AWS X-Ray (sale path)** | `sale-payment-callback-20260921.md` + JSON | Payments + POS settlement traced in dev |
| **AWS X-Ray (commission service)** | No traces in last 24h | Commission worker had no scheduled-close traffic in dev during capture window |

Commission ECS did not emit X-Ray segments in the capture window (`get-trace-summaries` filter `service(id(name: "commission"))` → 0). That is expected when no `/internal/close` or worker cron ran against the shared DB in dev. The **Payments B2C handler** is the traced boundary commission must use; local e2e step 5 exercises that handler end-to-end with fake M-Pesa.

## Reproduce B2C contract (local, timed)

```bash
# Terminals 1–2: services/pos/local/run-pos.sh && run-payments.sh
services/pos/local/run-e2e.sh   # step 5 — B2C block
```

## Reproduce commission trace in AWS (when worker runs)

```bash
export AWS_PROFILE=group3 AWS_REGION=us-west-1
START=$(date -u -d '30 min ago' +%s); END=$(date -u +%s)
aws xray get-trace-summaries --start-time "$START" --end-time "$END" \
  --filter-expression 'service(id(name: "commission"))' \
  --output json > evidence/reliability/phase-f/traces/xray-summaries-commission-$(date -u +%Y%m%d).json
```

After triggering commission close on dev (shared DB + `DATABASE_URL` on commission task), expect spans on `commission` and downstream `payments` HTTP client.
