# ADR-001: AWS region

- **Status:** Accepted
- **DRI:** Lwam
- **Date:** 2026-09-08

## Context
The program assigns `us-west-1` (N. California) to this team; region is not a team choice. The
ADR's job is to document what that constraint actually means for the design and how we accommodate
it, not to re-litigate the choice.

`us-west-1` differs from the more commonly-used `us-west-2` in three ways that matter here:
1. Only **two** usable Availability Zones are generally available to new accounts (`us-west-1a`,
   `us-west-1b`); a third AZ exists for some legacy accounts but must not be assumed available.
2. It is a **thinner** region (~161 services) — notably, **Amazon Managed Grafana is not offered
   there**.
3. **Amazon Managed Service for Prometheus (AMP) is available** (GA'd there September 2025), so a
   managed metrics backend is not blocked.
4. Per-resource cost runs higher than `us-west-2` for several services (compute, some managed
   services).

## Decision
Accept `us-west-1` as assigned and design around its gaps:
- **Pin AZs explicitly**: `us-west-1a` and `us-west-1b`, hardcoded in Terraform (see
  [ADR-010](ADR-010-networking-topology.md)), never derived from `data.aws_availability_zones`
  with an assumed count — a 3rd-AZ assumption would silently break for teammates on accounts that
  don't have it.
- **Metrics**: use Amazon Managed Service for Prometheus as the metrics backend (remote-write from
  the ADOT collector sidecar on every ECS task), supplemented by CloudWatch for AWS-managed-service
  metrics (ALB, NAT, RDS) that don't flow through OTel.
- **Dashboards**: self-host Grafana on ECS Fargate (its own small service, own task definition,
  behind the same private-networking pattern as the application services) since Amazon Managed
  Grafana isn't available in-region. Grafana state (dashboards, datasources) is provisioned as
  code, not persisted click-ops, so the self-hosted instance is disposable/rebuildable.
- **Cost**: the higher per-resource cost vs. `us-west-2` is accepted and tracked explicitly in
  `docs/production-readiness.md`'s cost estimate rather than treated as a surprise later.

## Alternatives considered
- **CloudWatch-only dashboards, no Grafana** — rejected: loses a single pane of glass across AMP +
  CloudWatch + X-Ray, and the brief's dashboard-as-evidence requirement (ADR-008) is easier to meet
  with portable, exportable Grafana JSON than with CloudWatch dashboard JSON.
- **Self-hosted Prometheus instead of AMP** — rejected: AMP is available in-region now, and running
  our own Prometheus (storage, HA, scaling) is operational burden the team doesn't need to take on
  for a capstone-scale workload.
- **Auto-discover AZs at apply time** (`data.aws_availability_zones` + `slice(..., 0, 2)`) —
  rejected in favor of hardcoding: an auto-discovered AZ could differ per teammate's account
  entitlements and produce non-reproducible plans.

## Consequences
- Grafana is now a service the team operates and patches (its own ECS task, ALB target, and a small
  persistence concern for dashboard state) — not something AWS manages for us.
- Every module that needs an AZ list references the same two hardcoded AZs (`infra/modules` should
  expose them as a shared variable, not repeat the literals) — this is called out again in
  [ADR-010](ADR-010-networking-topology.md).
- AMP scrape/remote-write design (via the ADOT sidecar per task, see
  [ADR-008](ADR-008-telemetry-conventions.md)) is now load-bearing infrastructure, not optional.
- Cost is materially higher than `us-west-2` would have been; this is a fixed, accepted constraint
  and should not be re-raised as a blocker later.

## Required proof (from brief)
ADR + terraform plan — plan output attaches once `infra/envs/dev` exists and pins the two AZs
(tracked in [ADR-010](ADR-010-networking-topology.md)'s implementation).
