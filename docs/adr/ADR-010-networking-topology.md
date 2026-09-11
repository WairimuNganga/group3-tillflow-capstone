# ADR-010: Networking topology

- **Status:** Accepted
- **DRI:** Lwam
- **Date:** 2026-09-08

## Context
The edge must be managed and public; everything behind it — application and data — must be private,
spread across the two usable AZs from [ADR-001](ADR-001-aws-region.md), and no more exposed than
each component strictly needs.

## Decision
`WEB → API Gateway (HTTP API) → VPC Link → internal ALB → ECS Fargate services`, matching
`docs/architecture.md`:

- **Public subnets** (one per AZ: `us-west-1a`, `us-west-1c`) host NAT Gateway(s) only — nothing
  else public-facing lives here. The ALB itself is **internal**, reached exclusively through the
  VPC Link; it is never given a public IP or a public listener.
- **App private subnets** (one per AZ) host the ECS Fargate tasks and the internal ALB.
- **Data private subnets** (one per AZ) host RDS. These subnets have **no route to a NAT Gateway or
  Internet Gateway at all** — not just no public IP, no egress path to the internet, period.
- **NAT**: a single NAT Gateway for the `dev` environment, accepted as a documented single point of
  egress failure to control cost (logged in `docs/threat-model.md` and `docs/scar-log.md` so it
  isn't forgotten); one-per-AZ is the upgrade path before any drill that needs to prove AZ-independent
  egress.
- **Security groups**, least privilege, one per component:
  - ALB SG: inbound 443 only from the VPC Link's ENIs.
  - Each service SG: inbound only from the ALB SG, on that service's container port.
  - RDS SG: inbound 5432 only from the specific service SGs that need DB access — not a blanket
    "anything in the app tier" rule.
- No ECS task and no RDS instance is ever given a public IP.

## Alternatives considered
- **Public-facing ALB** — rejected: the brief requires private topology behind managed ingress, and
  a public ALB widens the attack surface for a system handling money and PII unnecessarily.
- **Two NAT Gateways in `dev`** — rejected on cost grounds for the non-prod environment; the
  single-NAT risk is accepted and documented rather than silently ignored.
- **Blanket "app tier" security group** shared across services — rejected: defeats the purpose of
  per-service isolation; a compromised or misconfigured service shouldn't inherit network access to
  every other service's port by default.

## Consequences
- The VPC Link adds a small amount of latency and has its own scaling/quota characteristics to
  monitor — not free relative to a directly public ALB.
- The single dev NAT Gateway is a known, accepted single point of egress failure; it must stay
  visible in `docs/threat-model.md`, not get lost once the network is up and "working."
- Every new service needs an explicit security group + rule added in the same PR that adds the
  service — documented as a checklist item in `infra/README.md`.
- Data subnets with zero internet route mean nothing in RDS's operation may depend on outbound
  internet access — true for RDS Postgres, but worth re-checking for any future data-tier addition.

## Required proof (from brief)
ADR + terraform plan (`infra/modules/vpc`, `infra/modules/api-gateway`, applied via
`infra/envs/dev`).
