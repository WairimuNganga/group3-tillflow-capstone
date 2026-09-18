# Migration convention (shared)

Every service's schema is created and populated by SQL migrations that run
**as that service's schema-owner role**, never as the RDS master user.

This is not a style preference — it is required by the way the G2 DB bootstrap
([`infra/modules/db-bootstrap/buildspec.yml`](../../../infra/modules/db-bootstrap/buildspec.yml))
sets the database up:

- The bootstrap creates a role pair per service, e.g. `tillflow_pos_owner`
  (`NOLOGIN`, owns the `pos` schema) and `tillflow_pos` (`LOGIN`, the runtime
  role the ECS task connects as).
- It runs `ALTER DEFAULT PRIVILEGES FOR ROLE tillflow_pos_owner IN SCHEMA pos
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tillflow_pos`.

Default privileges only fire for objects created **by the role named in the
`FOR ROLE` clause**. So a table created by the master user (or any role other
than `tillflow_pos_owner`) is invisible to the runtime role — the service would
start and then fail every query with `permission denied`. Running the migration
as the owner role is what makes the runtime grants materialise.

Both roles are created `NOBYPASSRLS` (see [ADR-005](../../../docs/adr/ADR-005-multi-tenancy-isolation.md)),
so Row-Level Security is enforced against the owner too — hence every
tenant-owned table needs `FORCE ROW LEVEL SECURITY`, not just `ENABLE`.

## Rules for every migration

1. Wrap the whole file in a single transaction (`BEGIN; … COMMIT;`).
2. First two statements are `SET ROLE tillflow_<svc>_owner;` then
   `SET search_path = <svc>;`. (`SET ROLE` does **not** apply the target role's
   own `search_path`, so set it explicitly.)
3. Make it re-runnable: `CREATE TABLE IF NOT EXISTS`, `CREATE OR REPLACE
   FUNCTION`, and `DROP POLICY IF EXISTS` before `CREATE POLICY`. Rebuild/destroy
   drills re-apply migrations from scratch.
4. **Tenant-owned tables** (anything a merchant's data lives in) MUST, per
   ADR-005:
   - carry `tenant_id uuid NOT NULL` (the `tenants` table itself uses its own
     `id` as the tenant key);
   - lead their hot-path indexes with `tenant_id`;
   - `ENABLE` **and** `FORCE ROW LEVEL SECURITY`;
   - have a `tenant_isolation` policy filtering on
     `current_setting('app.current_tenant_id', true)::uuid` (the `true`
     = missing_ok means an unset GUC yields **zero rows**, not an error —
     isolation tests assert absence of rows).
   - use **composite foreign keys carrying `tenant_id`**
     (`FOREIGN KEY (tenant_id, parent_id) REFERENCES parent (tenant_id, id)`)
     so a child row can never be attached to another tenant's parent. This
     requires a `UNIQUE (tenant_id, id)` on each referenced table.

Raw SQL or Alembic both work as long as the rules hold. Worked example (Alembic):
[`services/pos/alembic/env.py`](../../pos/alembic/env.py) +
[`0001_create_pos_core_tables.py`](../../pos/alembic/versions/0001_create_pos_core_tables.py).
With Alembic, `SET ROLE` must run **inside** `context.begin_transaction()` —
running it first opens an outer transaction on SQLAlchemy 2.0, Alembic never
commits, and the migration logs success while silently rolling back.
