# Commission — daily close worker

**Owner:** Joyce (Product + POS) · **Cross-review:** Hunter (B2C / money)

Calculates attendant commission from **paid** sales, writes an idempotent ledger,
and calls Payments `POST /payments/b2c`. **Never** calls Daraja.

## Endpoints

| Route | Purpose |
|-------|---------|
| `GET /health`, `/ready` | ECS probes |
| `GET /internal/summary` | Ledger + payout intents for tenant/period (demo UI) |
| `POST /internal/close` | Trigger daily close (local/demo; not on ALB) |
| `POST /internal/payout` | Submit one attendant B2C via Payments |

Production trigger: EventBridge → SQS `payout` (`commission.daily_close.requested`).

## Schema (`commission`)

- `close_runs` — one row per `payout_period`
- `commission_ledger` — unique `(tenant_id, payout_period, attendant_id, sale_id)`
- `payout_intents` — unique `(tenant_id, payout_period, attendant_id)`

`payout_period` is an **EAT (GMT+3 / Africa/Nairobi)** calendar day. Paid sales are
bucketed with `(settled_at AT TIME ZONE 'Africa/Nairobi')::date`. Timestamps remain UTC in storage.

## Cross-schema reads

- `payments.v_paid_sales_for_commission`
- `pos.v_sales_for_commission`
- `pos.v_commission_rates_current`
- `pos.v_attendants_for_payout`

## Local

```bash
cd services/_shared && pip install -e ".[dev]"
cd ../commission && pip install -e ".[dev]"

TILLFLOW_TELEMETRY_EXPORT=none COMMISSION_WORKER_ENABLED=false pytest -v

# API (in-memory stores when DATABASE_URL unset)
COMMISSION_WORKER_ENABLED=false \
  uvicorn commission.main:app --reload --port 8090
```

## Env

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` / `DB_CREDENTIALS` | Commission schema |
| `PAYMENTS_BASE_URL` | B2C target (`http://payments:8080` in ECS) |
| `PAYOUT_QUEUE_URL` | SQS; empty → in-memory queue |
| `COMMISSION_WORKER_ENABLED` | `false` in unit tests |

## Dockerfile

Extends `services/_shared/Dockerfile.base` — install with `.[aws]` for boto3.
