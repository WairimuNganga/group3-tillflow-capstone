# Local commission Postgres (optional)

Prefer the **shared** tillflow DB (same as POS/payments on port 5432) so close can
read `payments.v_paid_sales_for_commission` and the POS commission views:

```bash
# From repo root, with tillflow-pos-db running:
docker exec -i tillflow-pos-db psql -U tillflow -d tillflow < services/commission/local/init-db.sql

cd services/commission
export DATABASE_URL="postgresql+asyncpg://commission:secret@localhost:5432/tillflow"
export PAYMENTS_BASE_URL="http://127.0.0.1:8080"
python3 -m alembic upgrade head
uvicorn commission.main:app --reload --port 8090
```

Standalone commission-only Postgres (port 5433) still works for schema-only smoke tests,
but paid-sale close will stay empty without the POS/payments views:

```bash
cd services/commission/local
docker compose up -d
cd ..
export DATABASE_URL="postgresql+asyncpg://commission:secret@localhost:5433/tillflow"
python3 -m alembic upgrade head
```

Without `DATABASE_URL`, the service uses in-memory stores (unit tests / local smoke).
POS views require `app.current_tenant_id`; the Postgres readers set it per tenant.
