# Drill 1/2 deployed AWS supplement

Date: 2026-09-23 UTC / 2026-09-24 EAT  
Environment: AWS dev

This supplement closes the deployed-evidence nuance for Drills 1–2. The timed money-safety proof remains `drill-1-2-timed-20260922.log`; this run adds AWS POS → Payments trace and service logs from the deployed environment.

## Flow captured

- Deployed web/POS sale path exercised through the public API.
- POS called Payments during the payment flow.
- X-Ray trace `1-94dbe6a4-965419f4b305798c78322278` contains both `pos` and `payments`.

## Evidence

| Evidence | File |
|----------|------|
| POS logs | `evidence/reliability/drill-1-2-deployed-pos-20260923.log` |
| Payments logs | `evidence/reliability/drill-1-2-deployed-payments-20260923.log` |
| X-Ray summaries | `evidence/reliability/phase-f/traces/xray-drill-1-2-summaries-20260923.json` |
| Full X-Ray trace | `evidence/reliability/phase-f/traces/xray-drill-1-2-trace-20260923.json` |

## Verification command

```bash
jq -r '.Traces[0].Segments[].Document' \
  evidence/reliability/phase-f/traces/xray-drill-1-2-trace-20260923.json \
  | jq -r '.name' \
  | sort -u
```

Expected services:

```text
payments
pos
```

## Interpretation

The full timing and duplicate/reconcile assertions are still proven by the local Drill 1/2 log. This AWS supplement proves the deployed POS and Payments services participate in the same payment-flow trace, removing the earlier concern that Drill 1/2 evidence was only local.
