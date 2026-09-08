# ADR-005: Multi-tenancy isolation

- **Status:** Accepted
- **DRI:** Joyce
- **Date:** 2026-09-08

## Context
TillFlow serves many tenants (merchants) from shared service instances and, per
[ADR-002](ADR-002-database.md), a single RDS instance with one schema per service. Within each
service's schema, one tenant's rows must never be readable or writable by another tenant's
requests — including through a bug in application code, not only through a deliberate attack.

## Decision
**Row-level `tenant_id` scoping**, enforced at two layers:

1. **Schema**: every tenant-owned table carries a `tenant_id` column (`NOT NULL`, FK to `tenants`),
   with a composite index leading with `tenant_id` on every hot query path.
2. **Database-enforced (defense in depth)**: Postgres Row-Level Security is enabled on every
   tenant-owned table. Each service's request-handling middleware runs
   `SET LOCAL app.current_tenant_id = $1` at the start of the request's transaction; RLS policies
   filter every statement against `current_setting('app.current_tenant_id')`. Every per-service DB
   role (from [ADR-002](ADR-002-database.md)) has `BYPASSRLS` explicitly revoked — including the
   role owner, so an admin connection can't accidentally see cross-tenant data either.

Application code is still expected to scope queries by `tenant_id` explicitly — RLS is the backstop
that catches the case where it doesn't, not a replacement for careful query-writing.

## Alternatives considered
- **Schema-per-tenant** — rejected: migrations would need to run against every tenant schema, and
  connection/pool management gets materially harder as tenant count grows; doesn't fit a model with
  many small tenants rather than a few large ones.
- **Database-per-tenant** — rejected: same multiplication problem as schema-per-tenant, worse, and
  directly conflicts with the single-instance design in [ADR-002](ADR-002-database.md).
- **Application-level `WHERE tenant_id = ?` only, no RLS** — rejected as the sole mechanism: one
  missed `WHERE` clause anywhere across five services becomes a cross-tenant data leak. RLS is cheap
  insurance against exactly that class of bug.

## Consequences
- Every new table migration must add `tenant_id`, enable RLS, and write the policy — this is now a
  checklist item in the shared migration template in `services/_shared`, and its absence should be a
  PR review blocker.
- Every request path must set the session GUC before querying; the DB middleware in
  `services/_shared` that does this becomes a hard dependency for every service.
- Cross-tenant isolation tests must assert **absence** of rows (RLS filters silently), not a thrown
  exception — test suites need to be written with that in mind, not assume a policy violation
  raises an error.

## Required proof (from brief)
ADR + tests: an RLS cross-tenant isolation test suite in `services/_shared`, exercised by each
service against its own schema.
