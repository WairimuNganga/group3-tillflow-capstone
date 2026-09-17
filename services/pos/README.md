# pos

Owner: Joyce (Product + POS). Point-of-sale sale-creation flow.

FastAPI service (`pos/`), Alembic schema migrations (`alembic/`), and a
Postgres-backed test suite (`tests/`). The data boundary (schema, roles, RLS) is
in [`alembic/versions/0001_create_pos_core_tables.py`](alembic/versions/0001_create_pos_core_tables.py).

Dockerfile: extend `services/_shared/Dockerfile.base` following the pattern in
[`services/_shared/examples/Dockerfile`](../_shared/examples/Dockerfile) — do not write a Dockerfile from scratch.

## API

Tenant scope comes from the `X-Tenant-Id` header (bound to the request context
by the shared telemetry middleware, then pushed into `app.current_tenant_id` for
RLS). Sale creation requires an `Idempotency-Key` header.

| Method & path | Purpose |
|---|---|
| `POST /tenants` | onboard a tenant + owner (mints the tenant id) |
| `POST /tills` | add a till (needs `X-Tenant-Id`) |
| `POST /attendants` | add an attendant (needs `X-Tenant-Id`) |
| `POST /sales` | create a sale — idempotent on `Idempotency-Key` |
| `GET /sales/{id}` | fetch a sale (RLS-scoped; other tenants get 404) |
| `GET /sales` | list this tenant's sales |
| `POST /sales/{id}/transition` | drive the sale state machine |
| `GET /health`, `GET /ready` | golden-path probes (`/ready` checks the DB) |

Sale states: `pending → awaiting_payment → paid`; `→ failed`;
`pending → cancelled`. Terminal states never transition again — the defence in
depth that stops a replayed payments callback re-driving a `paid` sale.

## Run it

```bash
pip install -e ../_shared -e '.[dev,prod]'
export DATABASE_URL="postgresql+asyncpg://tillflow_pos:***@localhost:5432/tillflow"
uvicorn pos.main:app --port 8000
```

Local Postgres with the same role split: [`local/README.md`](local/README.md).

**In AWS** there is no `DATABASE_URL`. ECS injects `DB_CREDENTIALS` — the `pos`
key of the `devops-g3/db` secret (`{username, password, host, port, dbname,
sslmode}`, runtime role `tillflow_pos`) — and `pos/config.py` builds the URL
from it, with TLS on because RDS Proxy has `require_tls = true`. Everyone shares
one database (`tillflow` behind
`devops-g3-db-proxy.proxy-chgiwkc8muat.us-west-1.rds.amazonaws.com`); isolation
between services is the per-service schema + role, not separate databases.
Never put the password in `.env`, chat, or evidence.

## Tests

See [`tests/README.md`](tests/README.md). `pytest` skips the DB-backed suites
when `POS_TEST_ADMIN_DSN` is unset; with a Postgres it runs **32 tests** covering
the state machine, idempotency, tenant isolation, the E2E flow, and ECS DB wiring.

## Data model (`pos` schema)

All tables live in the `pos` schema, created and owned by `tillflow_pos_owner`;
the runtime role `tillflow_pos` connects with `search_path = pos`. See
[ADR-005](../../docs/adr/ADR-005-multi-tenancy-isolation.md),
[ADR-004](../../docs/adr/ADR-004-idempotency-and-money-integrity.md), and
[ADR-002](../../docs/adr/ADR-002-database.md).

| Table | Purpose | Tenant key | Notable tenant-scoped constraints |
|-------|---------|-----------|-----------------------------------|
| `tenants` | the merchant | its own `id` | RLS on `id`; canonical tenant registry for the product side |
| `users` | owner + attendants (phone = PII) | `tenant_id` | `UNIQUE (tenant_id, phone)`, `UNIQUE (tenant_id, id)` |
| `tills` | M-Pesa till/shortcode(s) | `tenant_id` | `UNIQUE (tenant_id, shortcode)`, `UNIQUE (tenant_id, id)` |
| `commission_rates` | per-attendant rate (integer bps) | `tenant_id` | FK `(tenant_id, attendant_id) → users` |
| `sales` | sale aggregate + state machine | `tenant_id` | `UNIQUE (tenant_id, idempotency_key)`; composite FKs to `tills`/`users` |
| `sale_items` | line items (minor units) | `tenant_id` | composite FK `(tenant_id, sale_id) → sales` ON DELETE CASCADE |

Design invariants:

- **Money is integer minor units** everywhere (`total_minor`, `*_minor bigint`;
  `rate_bps integer`). No floats.
- **Sale creation is idempotent per tenant** via `UNIQUE (tenant_id,
  idempotency_key)`.
- **Sale state machine**: `pending → awaiting_payment → paid`; `→ failed`;
  `pending → cancelled` (CHECK-constrained).
- **Every child FK carries `tenant_id`** (composite FK to a `UNIQUE (tenant_id,
  id)` parent), so a row can never be attached to another tenant's parent.

## Tenant isolation (RLS)

Every table has `ENABLE` + `FORCE ROW LEVEL SECURITY` with a `tenant_isolation`
policy filtering on `current_setting('app.current_tenant_id', true)::uuid`. The
service's request middleware must run `SET LOCAL app.current_tenant_id = <uuid>`
at the start of each request transaction. An unset GUC yields **zero rows**, not
an error — isolation tests assert absence of rows (ADR-005).

`FORCE` is required because `tillflow_pos_owner` is `NOBYPASSRLS` and owns the
tables; without it the owner would bypass the policy during migrations/maintenance.

## Migrations

Alembic, applied as the schema-owner role (`alembic/env.py` does `SET ROLE
tillflow_pos_owner` inside the migration transaction). Convention and rationale:
[`services/_shared/migrations/README.md`](../_shared/migrations/README.md).

```bash
cd services/pos
POS_DB_ADMIN_URL="postgresql+asyncpg://<owner-member>:***@<host>:5432/tillflow?ssl=require" \
  python -m alembic upgrade head
```

The connecting role must be a member of `tillflow_pos_owner` (in AWS, the RDS
master user is, courtesy of the G2 bootstrap). Migrations are re-runnable, so
destroy/rebuild drills re-apply cleanly.
