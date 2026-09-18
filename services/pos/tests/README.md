# POS tests

Two tiers:

- **No database** (`test_state_machine.py`, `test_sale_flow.py`,
  `test_config.py`) — domain rules, the API on in-memory stores, and the ECS
  `DB_CREDENTIALS` → URL wiring. Always run.
- **Postgres-backed** (`test_rls_isolation.py`) — needs a real Postgres because
  RLS / FORCE / composite FKs can't be exercised on SQLite. **Skips** (not fails)
  when `POS_TEST_ADMIN_DSN` is unset, so `pytest` is green on a laptop with no DB.

The harness (`conftest.py`) creates the `tillflow_pos` / `tillflow_pos_owner`
role pair (the pos slice of the G2 bootstrap), applies the real
Alembic migration (`alembic upgrade head`), and drives the app as the `NOBYPASSRLS` runtime role
— so isolation tests prove the same policies that run in AWS.

## Run against a throwaway Postgres

```bash
# 1. start a throwaway cluster (needs postgresql client + server on PATH)
export LC_ALL=C LANG=C
initdb -D /tmp/pgpos -U postgres --auth=trust --locale=C -E UTF8  # UTF8: psycopg3 breaks on SQL_ASCII
pg_ctl -D /tmp/pgpos -o "-p 5433 -k /tmp -c listen_addresses=localhost" -w start
createdb -h 127.0.0.1 -p 5433 -U postgres tillflow

# 2. run the suite
cd services/pos
pip install -e ../_shared -e '.[dev]'
export TILLFLOW_TELEMETRY_EXPORT=none
export POS_TEST_ADMIN_DSN="postgresql://postgres@127.0.0.1:5433/tillflow"
pytest -q

# 3. tear down
pg_ctl -D /tmp/pgpos stop -m immediate && rm -rf /tmp/pgpos
```

In CI, a `postgres` service container supplies `POS_TEST_ADMIN_DSN`.
