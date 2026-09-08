# ADR-009: CI/CD promotion & rollback

- **Status:** Accepted
- **DRI:** Wairimu
- **Date:** 2026-09-08

## Context
Five services, deployed to shared infrastructure, need a pipeline where what's running is always
traceable to an exact commit, deploys can be gated on health rather than hope, and a rollback is a
fast, pre-rehearsed action rather than an improvised rebuild.

## Decision
- **Artifact identity**: every push to `main` builds one container image per changed service,
  tagged with the immutable commit SHA
  (`<account_id>.dkr.ecr.us-west-1.amazonaws.com/tillflow-<service>:<sha>`). **`latest` is never
  used** — an image tag always names exactly one build.
- **CI gate** (`.github/workflows/ci.yml`, required check on `main`): build, test, and validate on
  every PR and push. A separate `release.yml` job on `main` builds and scans each changed service's
  image; the pipeline **fails on any fixable HIGH/CRITICAL** vulnerability finding. A finding that's
  not currently fixable is not a silent pass — it's logged as an accepted risk in
  `docs/scar-log.md`, not swallowed.
- **Promotion rule**: promotion is strictly commit-SHA-forward. Deploying an older SHA is never done
  by rebuilding it — it's an explicit, logged rollback action (below) using the already-built image.
  Only environments defined under `infra/envs/*` are valid deploy targets.
- **Deploy health gate**: the ECS service updates its task definition to the new image digest and
  deploys via `aws ecs update-service`, with the ECS **deployment circuit breaker** enabled
  (automatic rollback if the service fails to reach steady state) plus a post-deploy check hitting
  each service's `/healthz` for N consecutive successes before the deployment counts as promoted.
- **Rollback trigger**: automatic when the circuit breaker trips, or when the post-deploy health
  check fails N times within M minutes. Manual rollback is "redeploy the last-known-good SHA's
  already-built image" — never a rebuild — run via
  `gh workflow run rollback.yml -f sha=<previous-good-sha>`, and logged in `docs/runbook.md` plus
  `evidence/delivery/`.
- **Branch protection on `main`**: PR required, CODEOWNERS review required, and the `validate` job
  in `ci.yml` (plus `release.yml`'s scan job once services exist) set as required status checks —
  this ADR is the source of truth for which checks branch protection should require.

## Alternatives considered
- **Deploy from a developer's laptop / local `terraform apply`** — rejected: no audit trail, no
  repeatable artifact identity, and it's exactly the "immutable artifact" requirement the brief
  calls out.
- **Tag images `latest` and redeploy the same tag to roll back** — rejected: makes it ambiguous
  which build is actually running at any moment, and directly conflicts with the immutability
  requirement.
- **Blue/green via a second ECS service + weighted ALB traffic shift** — considered as a stronger
  future option; rejected for G0/G1 as more infrastructure than the team can stand up and prove
  working in the available time. The ECS deployment circuit breaker plus a rolling update captures
  most of the safety for far less infra.

## Consequences
- ECR repos need a lifecycle policy with a **minimum retention count**, not just an age cutoff —
  rollback depends on old images still existing, so age-only cleanup could delete the very image a
  rollback needs.
- `ci.yml`'s `validate` job (and `release.yml`'s scan job, once it exists) are the concrete required
  checks referenced by the branch-protection setup described in
  [Repo bootstrap](../../README.md) — if this ADR changes which checks matter, branch protection
  must be updated in the same PR.
- The team must actually rehearse a rollback before grading, to produce the rollback-log evidence
  this ADR requires — a rollback path that's only ever been read about, not exercised, doesn't count
  as proven.

## Required proof (from brief)
Pipeline evidence + rollback log, filed under `evidence/delivery/`.
