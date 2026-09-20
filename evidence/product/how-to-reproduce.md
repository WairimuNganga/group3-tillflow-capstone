# Product + POS — how to reproduce (G2)

DRI: Joyce. Everything below runs from a clean checkout against throwaway
Postgres; no AWS access, no Daraja, no real money (the fake M-Pesa adapter). It
proves the money-correctness and tenant-isolation invariants this area is graded
on, plus the POS ↔ Payments handoff that makes `sale → STK → callback → paid`
one automatic chain.

| Part | What it proves | Time |
|------|----------------|------|
| [1](#1-schema--rls-boundary) | schema owned by the owner role; RLS enabled **and** forced | ~1 min |
| [2](#2-pos-test-suite) | state machine, idempotency, isolation, payment handoff — 46 tests | ~1 min |
| [3](#3-two-service-flow-pos--payments) | the live cross-service flow — 40 assertions | ~3 min |

## 1. Schema + RLS boundary

Migrations apply as `tillflow_pos_owner`, never the master user — the runtime
role's grants only materialise for objects the owner created
([`services/_shared/migrations/README.md`](../../services/_shared/migrations/README.md)).

```bash
export LC_ALL=C LANG=C
# -E UTF8 matters: on a SQL_ASCII cluster psycopg3 returns bytes and Alembic crashes
initdb -D /tmp/pgpos -U postgres --auth=trust --locale=C -E UTF8
pg_ctl -D /tmp/pgpos -o "-p 5433 -k /tmp -c listen_addresses=localhost" -w start
createdb -h 127.0.0.1 -p 5433 -U postgres tillflow
export PGHOST=127.0.0.1 PGPORT=5433 PGUSER=postgres

# pos slice of the G2 bootstrap (roles + schema + default privileges)
psql -d tillflow -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE tillflow_pos_owner NOLOGIN NOBYPASSRLS;
CREATE ROLE tillflow_pos LOGIN PASSWORD 'x' NOBYPASSRLS;
CREATE SCHEMA IF NOT EXISTS pos AUTHORIZATION tillflow_pos_owner;
GRANT tillflow_pos_owner TO postgres;
GRANT CONNECT ON DATABASE tillflow TO tillflow_pos;
GRANT USAGE ON SCHEMA pos TO tillflow_pos;
ALTER DEFAULT PRIVILEGES FOR ROLE tillflow_pos_owner IN SCHEMA pos
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tillflow_pos;
ALTER ROLE tillflow_pos SET search_path = pos;
SQL

python3.11 -m venv .venv && . .venv/bin/activate
pip install -e services/_shared -e 'services/pos[dev]' -e 'services/payments[dev]'
export TILLFLOW_TELEMETRY_EXPORT=none

(cd services/pos && POS_DB_ADMIN_URL="postgresql+asyncpg://postgres@127.0.0.1:5433/tillflow" \
  python -m alembic upgrade head)

psql -d tillflow -tAc "select relname, pg_get_userbyid(relowner), relrowsecurity, relforcerowsecurity
  from pg_class where relnamespace='pos'::regnamespace and relkind='r'
  and relname <> 'alembic_version' order by 1;"
```

Expected: six rows (`commission_rates`, `sale_items`, `sales`, `tenants`,
`tills`, `users`), each `tillflow_pos_owner|t|t` — owner-owned, RLS **enabled**
and **forced**.

## 2. POS test suite

```bash
export POS_TEST_ADMIN_DSN="postgresql://postgres@127.0.0.1:5433/tillflow"
cd services/pos && pytest -q          # -> 46 passed
```

| Suite | Invariant |
|-------|-----------|
| `test_state_machine.py` | legal/illegal transitions; terminal states have no exits |
| `test_sale_flow.py` | one sale per `Idempotency-Key` (200 replay); same key across tenants allowed; missing key/tenant rejected; bad till rejected; attendant may cancel; **a public caller cannot mark a sale paid** |
| `test_payment_flow.py` | POS→Payments handoff sends the sale's own total; a retried handoff reaches one payment (no second prompt); unreachable Payments leaves the sale `awaiting_payment`, never declined; replayed result changes the sale once; wrong amount refused; cross-tenant result 404 |
| `test_rls_isolation.py` | migration leaves RLS enabled + forced; tenant B gets 404 for A's sale; RLS holds on a raw runtime-role connection; unset tenant → zero rows, not an error; `WITH CHECK` blocks cross-tenant insert |
| `test_config.py` | ECS `DB_CREDENTIALS` → runtime URL with TLS to RDS Proxy; explicit `DATABASE_URL` wins |

Payments' own suite (Hunter's area, includes the notification contract POS
depends on): `cd services/payments && MPESA_ADAPTER=fake pytest -q` → 49 passed.

## 3. Two-service flow (POS ↔ Payments)

Both services against one Postgres, separate schemas — the shape AWS uses.
Recorded run: [`e2e-flow-output.txt`](e2e-flow-output.txt).

```bash
# 1. database (POS_DB_PORT avoids a Homebrew Postgres on 5432)
cd services/pos/local && POS_DB_PORT=5440 docker compose up -d
docker exec -i tillflow-pos-db psql -U tillflow -d tillflow < ../../payments/local/init-db.sql

# 2. migrations
(cd services/pos && POS_DB_ADMIN_URL="postgresql+asyncpg://tillflow:secret@localhost:5440/tillflow" \
  python -m alembic upgrade head)
(cd services/payments && DATABASE_URL="postgresql+asyncpg://payments:secret@localhost:5440/tillflow" \
  python -m alembic upgrade head)

# 3. POS (terminal 2) — PAYMENTS_BASE_URL is what makes the handoff possible
cd services/pos && DATABASE_URL="postgresql+asyncpg://tillflow_pos:pos_secret@localhost:5440/tillflow" \
  PAYMENTS_BASE_URL="http://127.0.0.1:8080" TILLFLOW_TELEMETRY_EXPORT=none \
  uvicorn pos.main:app --port 8000

# 4. Payments (terminal 3) — POS_BASE_URL is how the outcome gets back
cd services/payments && DATABASE_URL="postgresql+asyncpg://payments:secret@localhost:5440/tillflow" \
  POS_BASE_URL="http://127.0.0.1:8000" TILLFLOW_TELEMETRY_EXPORT=none MPESA_ADAPTER=fake \
  uvicorn payments.main:app --port 8080

# 5. the flow (terminal 4)
services/pos/local/e2e-flow.sh          # -> 40 passed, 0 failed
```

What the run asserts, in order:

| Step | Invariant proved |
|------|------------------|
| sale → `/sales/{id}/pay` → STK | POS hands off with the sale's own total; 12500 minor units → 125 whole KES at the M-Pesa boundary |
| retry `/pay` | same payment returned — a retried till never prompts the customer twice |
| callback → POS | Payments reports the outcome; the sale becomes `paid` with **no manual step**, and the M-Pesa receipt is stored on it |
| duplicate callback | `duplicate_callback`, no second ledger entry, one sale state change |
| forced timeout | payment `pending_reconciliation` (not failed), sale not marked failed; reconcile settles it once and reports to POS |
| B2C payout | commission pays through Payments, never Daraja; re-running the close returns the same payout |
| cross-tenant | shop B cannot read, cancel, or settle shop A's sale (404 on both public and internal endpoints) |
| privilege | a public caller cannot set `paid`/`failed` (400); a result whose amount ≠ the sale total is refused (409); a forged callback URL is rejected (403) |

## 4. Teardown

```bash
pg_ctl -D /tmp/pgpos stop -m immediate && rm -rf /tmp/pgpos
cd services/pos/local && docker compose down -v
```

## Artefacts / links

- Schema + RLS: [`0001_create_pos_core_tables.py`](../../services/pos/alembic/versions/0001_create_pos_core_tables.py);
  payment references on the sale: [`0002_sale_payment_reference.py`](../../services/pos/alembic/versions/0002_sale_payment_reference.py)
- Handoff code: [`pos/clients/payments.py`](../../services/pos/pos/clients/payments.py) (POS → Payments),
  [`pos/api/internal.py`](../../services/pos/pos/api/internal.py) (Payments → POS),
  [`payments/clients/pos.py`](../../services/payments/payments/clients/pos.py) (the caller, in Hunter's area)
- Flow script: [`services/pos/local/e2e-flow.sh`](../../services/pos/local/e2e-flow.sh);
  POS-only script: [`e2e-demo.sh`](../../services/pos/local/e2e-demo.sh)
- ADRs: [ADR-005 (tenancy)](../../docs/adr/ADR-005-multi-tenancy-isolation.md),
  [ADR-004 (idempotency & money)](../../docs/adr/ADR-004-idempotency-and-money-integrity.md)

## Current status / known gaps

- **POS ↔ Payments handoff is provisioned in AWS.** The ECS tasks carry
  `PAYMENTS_BASE_URL=http://payments:8080` and `POS_BASE_URL=http://pos:8080`,
  and the public edge blocks `/api/pos/internal/*`.
- **POS migrations run before ECS deploy.** CodePipeline stage `MigrateDb`
  runs `pos-alembic` from the built POS image before `DeployEcs`.
- **Payments `/ready` is fixed.** The sync DB health path now uses a libpq-safe
  DSN, so healthy ECS payments tasks stay in service.
- **Commission worker exists.** See
  [`commission-close-b2c.md`](./commission-close-b2c.md) for daily close →
  payout ledger → B2C evidence and reproduce commands.
- **Refund / reversal flow** is still not designed; it needs its own states and
  ledger treatment.
