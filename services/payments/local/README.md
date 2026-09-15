# Local Postgres for Payments

Use this while waiting on AWS RDS. Same migrations (`alembic upgrade head`) apply later
against the real DB — only `DATABASE_URL` changes.

## Start

```bash
cd services/payments/local
docker compose up -d
```

Wait until healthy:

```bash
docker compose ps
```

If you already started the DB **before** this privilege fix, either recreate:

```bash
docker compose down -v && docker compose up -d
```

or grant on the running instance:

```bash
docker exec -it tillflow-payments-db \
  psql -U tillflow -d tillflow \
  -c 'GRANT CONNECT, CREATE ON DATABASE tillflow TO payments;'
```

## Migrate

```bash
cd services/payments
export DATABASE_URL="postgresql+asyncpg://payments:secret@localhost:5432/tillflow"
python3 -m alembic upgrade head
```

## Run the API against Postgres

```bash
cd services/payments
export DATABASE_URL="postgresql+asyncpg://payments:secret@localhost:5432/tillflow"
export TILLFLOW_TELEMETRY_EXPORT=none
export MPESA_ADAPTER=fake
python3 -m uvicorn payments.main:app --reload --port 8080
```

Check:

- http://127.0.0.1:8080/health → `200`
- http://127.0.0.1:8080/ready → `200` (DB reachable)

## Stop / reset

```bash
cd services/payments/local
docker compose down          # keep data volume
docker compose down -v       # wipe DB and re-run init-db.sql on next up
```

## Connection details

| Setting | Value |
|---|---|
| Host | `localhost:5432` |
| Database | `tillflow` |
| App user | `payments` / `secret` |
| Schema | `payments` |
| `DATABASE_URL` | `postgresql+asyncpg://payments:secret@localhost:5432/tillflow` |
