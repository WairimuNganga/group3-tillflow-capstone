# Product + POS — how to reproduce (G2)

DRI: Joyce. Everything below runs from a clean checkout against a throwaway
Postgres; no AWS access needed. It proves the money-correctness and
tenant-isolation invariants this area is graded on.

## 1. Schema + RLS boundary (migration applies as owner, RLS enforced)

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

# apply the real Alembic migration as the owner role
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e services/_shared -e 'services/pos[dev]'
export TILLFLOW_TELEMETRY_EXPORT=none
(cd services/pos && POS_DB_ADMIN_URL="postgresql+asyncpg://postgres@127.0.0.1:5433/tillflow" \
  python -m alembic upgrade head)

# expect: every table owned by tillflow_pos_owner, RLS enabled AND forced
psql -d tillflow -tAc "select relname, pg_get_userbyid(relowner), relrowsecurity, relforcerowsecurity
  from pg_class where relnamespace='pos'::regnamespace and relkind='r'
  and relname <> 'alembic_version' order by 1;"
```

Expected: six rows (`commission_rates`, `sale_items`, `sales`, `tenants`,
`tills`, `users`), each `tillflow_pos_owner|t|t`.

## 2. Behaviour: isolation, idempotency, state machine, money

```bash
export POS_TEST_ADMIN_DSN="postgresql://postgres@127.0.0.1:5433/tillflow"
cd services/pos && pytest -q
```

Expected: `32 passed`. What each suite proves:

| Suite | Invariant |
|-------|-----------|
| `test_state_machine.py` | legal/illegal sale transitions; terminal states have no exits; same-state is not a transition |
| `test_sale_flow.py` | onboard → sell; same `Idempotency-Key` → one sale (200 replay); same key across tenants allowed; missing key / tenant rejected; bad till rejected; `pending→awaiting_payment→paid`; illegal transition 409; duplicate transition is a no-op |
| `test_rls_isolation.py` | migration leaves RLS enabled + forced; tenant B gets 404 for A's sale; lists scoped; RLS holds on a raw runtime-role connection; unset tenant → zero rows, not an error; `WITH CHECK` blocks cross-tenant insert |
| `test_config.py` | ECS `DB_CREDENTIALS` JSON → runtime URL with TLS to RDS Proxy; special chars in password survive; explicit `DATABASE_URL` wins |

## 3. Teardown

```bash
pg_ctl -D /tmp/pgpos stop -m immediate && rm -rf /tmp/pgpos
```

## Artefacts / links

- Schema + RLS: [`services/pos/alembic/versions/0001_create_pos_core_tables.py`](../../services/pos/alembic/versions/0001_create_pos_core_tables.py)
- Migration convention: [`services/_shared/migrations/README.md`](../../services/_shared/migrations/README.md)
- ADRs: [ADR-005 (tenancy)](../../docs/adr/ADR-005-multi-tenancy-isolation.md),
  [ADR-004 (idempotency & money)](../../docs/adr/ADR-004-idempotency-and-money-integrity.md)
- Service code: [`services/pos/pos/`](../../services/pos/pos)

## Known follow-ups (out of G2 scope)

- Refund / reversal flow (platform handover lists this as a POS input) — not yet
  designed; needs its own state(s) and ledger treatment.
- Read-only `paid_sales` view in the `pos` schema granted to `tillflow_commission`
  (ADR-002 cross-service read path) — lands with the commission worker.
