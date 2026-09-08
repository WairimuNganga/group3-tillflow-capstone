# ADR-002: Database (RDS PostgreSQL)

- **Status:** Accepted
- **DRI:** Lwam
- **Date:** 2026-09-08

## Context
Four services (`web`, `pos`, `payments`, `commission`) need durable relational storage with strict
per-service data ownership, on a budget and timeline that don't support running five separate
database instances in a region that already costs more than `us-west-2` ([ADR-001](ADR-001-aws-region.md)).

## Decision
One RDS PostgreSQL instance, one database, **one schema per service** with least-privilege roles:

- **Engine**: PostgreSQL 16.x (latest RDS-supported minor at deploy time, minor-version auto-upgrade
  on).
- **Instance class**: `db.t4g.medium` (Graviton, burstable) for `dev`/G0-G1 — cheapest class that
  comfortably fits capstone-scale load; documented upgrade path to an `r6g` class before any
  reliability drill that simulates production traffic.
- **Storage**: `gp3`, 20 GiB initial, storage autoscaling enabled up to 100 GiB. Baseline gp3
  IOPS/throughput (3,000 IOPS / 125 MB/s) is sufficient at this scale without paying for
  provisioned IOPS.
- **Multi-AZ**: **single-AZ** for `dev` (cost); **Multi-AZ standby** required before any drill or
  demo that claims production-like reliability — both usable AZs from
  [ADR-001](ADR-001-aws-region.md) support this without further region work.
- **Schemas & roles**: one Postgres schema per service (`pos`, `payments`, `commission`, `web`).
  One least-privilege role per service, granted `USAGE` + CRUD only on its own schema. No
  cross-schema table grants; where a service genuinely needs to read another's data (e.g.
  `commission` reading paid-sale totals owned by `payments`), that's exposed as an explicit
  read-only view in the owning schema, granted to the consuming role — never a raw cross-schema
  table grant. This is schema-level (service) isolation; **tenant**-level isolation within each
  service's schema is a separate, stricter mechanism — see [ADR-005](ADR-005-multi-tenancy-isolation.md).
- **Connection pooling**: RDS Proxy in front of the instance. Every ECS service connects through
  the proxy with its own schema-scoped credentials (pulled from Secrets Manager), so ECS task
  scale-out doesn't exhaust the instance's native connection limit.
- **Backups**: automated daily backups, 7-day retention for `dev`, backup window in low-traffic
  hours (03:00–04:00 UTC). Point-in-time recovery within the retention window satisfies an RPO of
  ≤24h with margin. Deletion protection enabled on the instance.

## Alternatives considered
- **Aurora PostgreSQL Serverless v2** — rejected for G0/G1: ACU tuning is another operational
  dimension the team doesn't need yet; standard RDS is simpler and predictable for this load.
- **Database-per-service or schema-per-tenant at the DB layer** — rejected: multiplies RDS
  instances (cost, on top of [ADR-001](ADR-001-aws-region.md)'s already-elevated per-resource
  cost) and multiplies migration/connection-management surface for marginal isolation benefit over
  schema + role separation.
- **Self-hosted PgBouncer on ECS instead of RDS Proxy** — rejected: RDS Proxy is managed, integrates
  with Secrets Manager/IAM auth, and is one less service the team has to patch and scale itself.

## Consequences
- One instance is a shared blast radius: a runaway query in one service can degrade another's
  latency. Mitigated by RDS Proxy connection limits per service credential and by keeping an eye on
  this in the per-service SLOs ([ADR-006](ADR-006-slos-and-error-budgets.md)).
- Cross-service reads only via views is a discipline every PR touching `commission` ↔ `payments`
  data must follow — enforced by CODEOWNERS review on `services/_shared` and the owning schema.
- Upgrading to Multi-AZ before a drill is a real infra change (not just a checkbox) — budget time
  for it, don't assume it's already in place.
- PITR is bounded by the 7-day retention window; anything older needs a manual snapshot taken in
  advance.

## Required proof (from brief)
ADR + terraform plan (`infra/modules/rds`, applied via `infra/envs/dev`).
