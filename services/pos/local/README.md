# Local Postgres for POS

Same migrations (`alembic upgrade head`) apply later against RDS — only the
connection URLs change. `init-db.sql` sets up the owner/runtime role split so
RLS behaves exactly as it will in AWS (the app connects as the NOBYPASSRLS
`tillflow_pos`; migrations run as `tillflow_pos_owner`).

## G2 stack (copy-paste, from repo root)

Use the scripts in this folder so you do not have to remember env var names
(POS reads **`DATABASE_URL`**, not `POS_DATABASE_URL`). Payments listens on
**8080** so `./e2e-flow.sh` works without `PAY_URL=…`.

```bash
cd ~/capstone/group3-tillflow-capstone
python3 -m venv .venv && source .venv/bin/activate
pip install -e services/_shared -e 'services/pos[dev]' -e 'services/payments[dev]'

services/pos/local/db-up.sh          # Postgres on 5440 + payments init SQL
services/pos/local/migrate-local.sh  # POS + payments Alembic

# Three terminals — if restart fails with "address already in use":
services/pos/local/stop-servers.sh

# Terminal 1 — leave running:
services/pos/local/run-pos.sh
# Terminal 2 — leave running:
services/pos/local/run-payments.sh
# Terminal 3 — only after both show "Uvicorn running":
services/pos/local/run-dev-check.sh  # optional quick probe
services/pos/local/run-e2e.sh        # -> 41 passed, 0 failed
```

If e2e prints step `0` and stops with no PASS/FAIL, POS was not up yet — start terminal 1
before terminal 3. `run-e2e.sh` now waits up to 45s and prints what to start if not ready.
```

Override port when 5432 is free: `POS_DB_PORT=5432 services/pos/local/db-up.sh`
(and use the same `POS_DB_PORT` for migrate + run scripts).

## Start (manual)

```bash
cd services/pos/local
docker compose up -d
docker compose ps        # wait until healthy
```

Port 5432 already taken (e.g. Homebrew Postgres)? `localhost:5432` will then
hit *that* server and fail with `role "tillflow" does not exist`. Pick another
port and use it in the URLs below instead of 5432:

```bash
lsof -nP -iTCP:5432 -sTCP:LISTEN   # who owns 5432?
POS_DB_PORT=5440 docker compose up -d
```

## Migrate (runs as the owner role via alembic/env.py)

```bash
cd services/pos
export POS_DB_ADMIN_URL="postgresql+asyncpg://tillflow:secret@localhost:5432/tillflow"
python3 -m alembic upgrade head
```

## Run POS and Payments together (the G2 flow)

One container, two schemas — the shape AWS uses. Add the payments role/schema to
this database, then run both services pointing at each other:

```bash
docker exec -i tillflow-pos-db psql -U tillflow -d tillflow < ../../payments/local/init-db.sql
(cd ../../payments && DATABASE_URL="postgresql+asyncpg://payments:secret@localhost:5440/tillflow" \
  python -m alembic upgrade head)
```

POS needs `PAYMENTS_BASE_URL`, Payments needs `POS_BASE_URL`; without them the
handoff 503s and no outcome is reported. Full commands and the checks the flow
asserts: [`evidence/product/how-to-reproduce.md`](../../../evidence/product/how-to-reproduce.md).

```bash
./e2e-flow.sh        # both services: 41 assertions
./e2e-demo.sh        # POS alone: 31 assertions
```

## Run the API against Postgres

```bash
cd services/pos
export DATABASE_URL="postgresql+asyncpg://tillflow_pos:pos_secret@localhost:5432/tillflow"
export PAYMENTS_BASE_URL="http://127.0.0.1:8080"
export TILLFLOW_TELEMETRY_EXPORT=none
python3 -m uvicorn pos.main:app --reload --port 8000
```

Check:

- http://127.0.0.1:8000/health → `200`
- http://127.0.0.1:8000/ready → `200` (DB reachable)

Run without a database (in-memory stores, no RLS) by simply not setting
`DATABASE_URL`.

## Stop / reset

```bash
cd services/pos/local
docker compose down          # keep data volume
docker compose down -v       # wipe DB and re-run init-db.sql on next up
services/pos/local/stop-servers.sh   # kill uvicorn on 8000/8080
```

## Connection details

| Setting | Value |
|---|---|
| Host | `localhost:5432` (or `5440` via `POS_DB_PORT`) |
| Database | `tillflow` |
| App (runtime) role | `tillflow_pos` / `pos_secret` (NOBYPASSRLS) |
| Migration/admin role | `tillflow` / `secret` (superuser) |
| Schema | `pos` |
| `DATABASE_URL` | `postgresql+asyncpg://tillflow_pos:pos_secret@localhost:5440/tillflow` |
| `POS_DB_ADMIN_URL` | `postgresql+asyncpg://tillflow:secret@localhost:5440/tillflow` |
| POS API | `http://127.0.0.1:8000` |
| Payments API | `http://127.0.0.1:8080` |
