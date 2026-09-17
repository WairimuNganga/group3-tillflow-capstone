# payments

Owner: Hunter (Payments + integrity). STK push, M-Pesa callback handling, B2C payouts,
reconciliation.

## Phase 0 — foundation

Runnable FastAPI service with `/health`, `/ready`, OTel bootstrap, Alembic wired to the
`payments` Postgres schema.

## Phase 1 — money + idempotency

- `tillflow_shared.money.kes` — minor-units ↔ whole-shilling conversion ([ADR-004])
- `tillflow_shared.idempotency` — FastAPI guard + `PostgresIdempotencyStore`
- Migration `0002_idempotency_keys` — tenant-scoped idempotency table

## Phase 2 — payment schema + state machines

Tables (migration `0003_payment_core_tables`):

| Table | Purpose |
|---|---|
| `payments` | One row per sale payment attempt |
| `payment_callbacks` | Raw Daraja payloads; unique on provider IDs |
| `payment_ledger` | Append-only money effects |
| `payouts` | B2C commission disbursements |

State machines live in `payments/domain/state.py` and are enforced in code before handlers
land in Phase 3+.

When RDS is available:

```bash
export DATABASE_URL=postgresql+asyncpg://payments:...@.../tillflow
alembic upgrade head   # 0001 schema → 0002 idempotency → 0003 core tables
```

## Phase 3 — STK Push

`POST /payments/stk` initiates M-Pesa STK for a POS sale.

```bash
curl -s -X POST http://127.0.0.1:8080/payments/stk \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-Id: tenant-a' \
  -H 'Idempotency-Key: sale-key-1' \
  -d '{
    "sale_id": "11111111-1111-1111-1111-111111111111",
    "phone_number": "254712345678",
    "amount_minor_units": 1500,
    "fake_scenario": "immediate_success"
  }'
```

- Amounts enter as **minor units**; converted via `to_whole_kes` before Daraja
- `AccountReference` = idempotency key
- Timeout → `pending_reconciliation` (never `failed`)
- Without `DATABASE_URL`, payments/idempotency use **in-memory** stores (local + CI)

## Phase 4 — callbacks

`POST /callbacks/mpesa/{callback_secret}` — public Daraja STK callback.

- Secret path segment authenticates the callback ([ADR-007])
- Upsert on `(merchant_request_id, checkout_request_id)` — exact replays are no-ops
- Settlement is **order-independent**: late success after failure → `paid`; failure after
  `paid` is ignored
- At most **one** `charge_confirmed` ledger entry per payment

```bash
# After STK (fake immediate_success), drain is internal — in drills/tests the fake
# adapter queues the Daraja-shaped body. Example shape:
curl -s -X POST http://127.0.0.1:8080/callbacks/mpesa/$MPESA_CALLBACK_SECRET \
  -H 'Content-Type: application/json' \
  -d @callback.json
```

Default local secret: `local-dev-callback-secret` (override with `MPESA_CALLBACK_SECRET`).

Phase 8 evidence pack: [`evidence/payments/mpesa-integration-manual-test.md`](../../evidence/payments/mpesa-integration-manual-test.md).

## Phase 7 — money invariants (crown jewels)

```bash
cd services/payments
TILLFLOW_TELEMETRY_EXPORT=none MPESA_ADAPTER=fake pytest tests/invariants -v
```

| Invariant | Test |
|---|---|
| Minor units + KES boundary | `test_kes_boundary_*`, `test_stk_persists_both_*` |
| STK idempotent (no double charge) | `test_stk_idempotency_no_double_charge` |
| Timeout ≠ decline → reconcile once | `test_timeout_stays_pending_then_resolves_once` |
| Callback replay → one ledger line | `test_callback_replay_one_ledger_entry` |
| Out-of-order callbacks → one settle | `test_out_of_order_callbacks_settle_once` |
| B2C replay → no double payout | `test_b2c_replay_no_double_payout` |
| Cross-tenant key isolation (M1) | `test_cross_tenant_idempotency_does_not_leak_response` |


## Phase 6 — B2C (Commission → Payments only)

`POST /payments/b2c` — Commission never calls Daraja directly.

```bash
curl -s -X POST http://127.0.0.1:8080/payments/b2c \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-Id: tenant-a' \
  -H 'Idempotency-Key: tenant-a:2026-09-14:attendant-7' \
  -d '{
    "attendant_id": "attendant-7",
    "phone_number": "254712345678",
    "amount_minor_units": 50000,
    "originator_conversation_id": "tenant-a:2026-09-14:attendant-7"
  }'

# ResultURL (async completion):
curl -s -X POST http://127.0.0.1:8080/payments/b2c/result \
  -H 'Content-Type: application/json' \
  -d '{"conversation_id":"<from submit>","success":true}'
```

- `Idempotency-Key` **must equal** `originator_conversation_id`
- Replay → same payout, no second Daraja call
- Success result → `completed` + one `payout_disbursed` ledger line


## Phase 5 — reconciliation

Timeout path: STK timeout → `pending_reconciliation` + outbox job → worker runs STK Query
→ same settlement as callbacks (`paid` / `failed`) → at most one ledger line.

```bash
# After a delayed_timeout STK:
curl -s -X POST http://127.0.0.1:8080/payments/reconcile/outbox
# Or one payment:
curl -s -X POST http://127.0.0.1:8080/payments/reconcile/<payment_id>
```

Local/CI uses an in-memory outbox. Deployed env will publish to the reconciliation
SQS queue (Lwam) — same `ReconciliationService.reconcile_payment` handler.

## Local development

Install shared first, then payments:

```bash
cd services/_shared && python3 -m pip install -e ".[dev]"
cd ../payments && python3 -m pip install -e ".[dev]"
```

### Optional: local Postgres

See [`local/README.md`](local/README.md). Quick start:

```bash
cd services/payments/local && docker compose up -d
cd ..
export DATABASE_URL="postgresql+asyncpg://payments:secret@localhost:5432/tillflow"
python3 -m alembic upgrade head
```

Without `DATABASE_URL`, the service uses **in-memory** stores (fine for unit/invariant tests).

### Optional: Daraja sandbox

See [`local/SANDBOX.md`](local/SANDBOX.md). Copy `.env.example` → `.env`, fill sandbox
creds, tunnel with ngrok, set `MPESA_ADAPTER=sandbox`.

Run:

```bash
export TILLFLOW_TELEMETRY_EXPORT=none
export DATABASE_URL=postgresql+asyncpg://payments:secret@localhost:5432/tillflow
uvicorn payments.main:app --reload --port 8080
```

Migrate (creates the `payments` schema):

```bash
cd services/payments
export DATABASE_URL=postgresql+asyncpg://payments:secret@localhost:5432/tillflow
alembic upgrade head
```

Test:

```bash
cd services/payments
TILLFLOW_TELEMETRY_EXPORT=none MPESA_ADAPTER=fake pytest -v
```

## Docker

Build the shared base first (`services/_shared`), then:

```bash
docker build -f services/payments/Dockerfile \
  --build-arg BASE_IMAGE=tillflow-base:local \
  --build-arg GIT_COMMIT_SHA=$(git rev-parse --short HEAD) \
  -t tillflow-payments:local \
  services/payments
```

## Environment

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Async Postgres URL (`postgresql+asyncpg://…`) |
| `MPESA_ADAPTER` | `fake` (CI/tests) or `sandbox` (deployed dev) |
| `GIT_COMMIT_SHA` | Exposed on `/health` |
| `TILLFLOW_TELEMETRY_EXPORT` | `none` in tests; `otlp` in ECS |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | ADOT sidecar (`http://localhost:4317`) |

Daraja variables are unused until Phase 3 — see `services/_shared/README.md`.
