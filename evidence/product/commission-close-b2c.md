# Commission close → B2C evidence

**Owner:** Joyce · **Cross-review:** Hunter  
**Date:** 2026-09-20  
**Branch:** feature work implementing `services/commission`

## What this proves

| # | Invariant | Test |
|---|-----------|------|
| 1 | Only paid+settled sales ledger | `test_only_paid_settled_sales_generate_ledger` |
| 2 | Close replay → no second B2C | `test_close_twice_same_period_no_second_b2c` |
| 3 | Idempotent attendant key | `test_attendant_key_replay_one_b2c_call` |
| 4 | Mid-batch resume pays only failed | `test_mid_batch_resume_pays_only_failed` |
| 5 | Rate change does not reprice ledger | `test_rate_change_does_not_reprice_ledgered_sales` |
| 6 | No Daraja / mpesa adapter in commission | `test_no_daraja_import_in_commission_package` |

## Reproduce

```bash
cd services/_shared && pip install -e ".[dev]"
cd ../commission && pip install -e ".[dev]"
TILLFLOW_TELEMETRY_EXPORT=none COMMISSION_WORKER_ENABLED=false pytest -v
```

## Cross-schema views (Hunter + Joyce + Lwam)

| View | Owner migration |
|------|-----------------|
| `payments.v_paid_sales_for_commission` | `services/payments/alembic/.../0004_paid_sales_commission_view.py` |
| `pos.v_sales_for_commission` | `services/pos/alembic/.../0003_commission_read_views.py` |
| `pos.v_commission_rates_current` | same |
| `pos.v_attendants_for_payout` | same |

Migrations grant `SELECT` to `tillflow_commission` when the role exists.

## B2C contract (commission → payments)

```
POST /payments/b2c
X-Tenant-Id: {tenant_id}
Idempotency-Key: {tenant_id}:{payout_period}:{attendant_id}

{
  "attendant_id": "...",
  "phone_number": "2547...",
  "amount_minor_units": 290,
  "originator_conversation_id": "{same as Idempotency-Key}"
}
```

## Manual smoke

```bash
# commission on :8090 (in-memory)
COMMISSION_WORKER_ENABLED=false uvicorn commission.main:app --port 8090

curl -s -X POST http://127.0.0.1:8090/internal/close \
  -H 'Content-Type: application/json' \
  -d '{"payout_period":"2026-09-19"}'
```

Unit tests seed paid sales into the in-memory reader; Postgres join path requires the views above after `alembic upgrade head` on payments + pos + commission.

## Demo UI (Hunter)

Shell evidence (attendant day + payouts table, EAT periods):
[`web-demo-shell.md`](web-demo-shell.md) screenshots **07–09**.

```bash
export COMMISSION_BASE_URL=http://127.0.0.1:8090
# then http://127.0.0.1:8070/commission and /payouts
```
