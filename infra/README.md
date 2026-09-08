# infra

Owner: Lwam (Platform). Terraform for VPC/networking, RDS, S3, ECS, API Gateway.

- `envs/` — per-environment root modules (backend config, variable values). `envs/dev/` is the
  first target.
- `modules/` — reusable Terraform modules referenced by each env.

Backed by [ADR-001](../docs/adr/ADR-001-aws-region.md) (region),
[ADR-002](../docs/adr/ADR-002-database.md) (database),
[ADR-003](../docs/adr/ADR-003-object-storage.md) (object storage),
[ADR-010](../docs/adr/ADR-010-networking-topology.md) (networking).

Scaffold placeholder — Terraform lands here in G1.
