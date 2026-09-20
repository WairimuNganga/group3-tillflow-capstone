# ADR-009: CI/CD promotion & rollback

- **Status:** Accepted
- **DRI:** Wairimu
- **Date:** 2026-09-08

## Context
Five services, deployed to shared infrastructure, need a pipeline where what's running is always
traceable to an exact commit, deploys can be gated on health rather than hope, and a rollback is a
fast, pre-rehearsed action rather than an improvised rebuild.

## Decision
- **Artifact identity**: each service has its own **immutable-tag** ECR repository
  (`devops-g3/<service>`, `image_tag_mutability = "IMMUTABLE"` — ECR itself rejects overwriting a
  tag, not just convention). CodePipeline's `BuildScanPush` stage tags every image with the
  resolved commit SHA (`CODEBUILD_RESOLVED_SOURCE_VERSION`). **`latest` is never used** — an image
  tag always names exactly one build, and re-running a build for a SHA that already has an image
  reuses it instead of rebuilding (`buildspecs/service-image.yml`'s `IMAGE_ALREADY_EXISTS` check),
  so promotion is idempotent.
- **Two CI/CD lanes, per the brief**:
  - **GitHub Actions** (`.github/workflows/ci.yml`, `terraform.yml`) — fast, pre-merge feedback:
    layout/ADR checks, unit tests per service, lint, secret/dependency scanning, a local
    build-and-scan of the golden-path image, and (`terraform.yml`) `fmt`/`validate`/`test` plus a
    read-only `terraform plan` against the real account on every PR touching `infra/**`. None of
    this lane pushes an image or touches a running service.
  - **AWS-native release pipeline** (`infra/modules/delivery`, driving `buildspecs/*.yml`) —
    CodeStarConnections (GitHub source) → CodePipeline → CodeBuild (`BuildScanPush`: mirror the
    pinned ADOT sidecar, then build+push+scan each service) → `MigrateDb` (POS, Payments and
    Commission Alembic migrations, in parallel)
    → `DeployEcs` → `Smoke` (scale up, wait for ECS stability, then `curl` the public `/health` and
    `/ready` routes through the real edge — API Gateway → VPC Link → ALB). This lane is what
    actually ships to `dev`, on every push to `main`.
- **Scan gate**: `BuildScanPush` runs `aws ecr start-image-scan` on the pushed tag and **fails the
  build on any *fixable* HIGH/CRITICAL** finding (a finding is fixable when ECR's advisory reports a
  `fixed_version`) — `buildspecs/service-image.yml`. A HIGH/CRITICAL finding with no fixed version
  yet is not a silent pass; it should be recorded in `docs/scar-log.md` with an owner and a
  re-check date, not left implicit.
- **Schema migrations gate the deploy**: `MigrateDb` runs one CodeBuild action per service that
  owns a schema (`pos-alembic`, `payments-alembic`, `commission-alembic`), all at `run_order = 1`
  so they execute in parallel — each owns a separate schema and never touches another's objects.
  A CodePipeline stage only completes when every action in it succeeds, so **`DeployEcs` starts
  only after all three migrations pass, and a failed migration stops the deployment**. This
  ordering is not cosmetic: a task started against a stale schema fails at *request* time, not
  deploy time — Payments served `500 UndefinedTableError` for exactly that reason while only POS
  migrations were wired in.
  - Each action runs `/opt/venv/bin/python -m alembic upgrade head` **inside the service image
    that was just built and scanned**, so the migration code and the application code are the same
    artifact. Re-running is safe: `upgrade head` is a no-op once the revision table is at head, so
    an unrelated redeploy does not re-apply migrations.
  - `alembic/env.py` issues `SET ROLE tillflow_<service>_owner` *inside* the migration transaction,
    so tables and `<schema>.alembic_version` are owned by the **owner** role, never the
    `NOBYPASSRLS` runtime role — a runtime role that owned its tables would bypass its own RLS
    policies (ADR-005). The connecting identity is the RDS master, which the db-bootstrap job made
    a member of each owner role.
  - The admin URL (`POS_DB_ADMIN_URL` / `PAYMENTS_DB_ADMIN_URL` / `COMMISSION_DB_ADMIN_URL`) is
    assembled inside the build from `MASTER_SECRET_ARN`, URL-quoted, and never echoed — so the
    master password is absent from Terraform state, the task definition, source control and build
    logs (threat model T6.3).
- **Promotion rule**: promotion is strictly commit-SHA-forward and only ever deploys an
  already-built image — never a rebuild of an old commit. Each service's selected `{tag, digest}`
  is the single source of truth in SSM (`/devops-g3/<service>/image-tag`,
  `.../image-digest`), written by the pipeline on a successful scan+push and read by both the
  `Smoke`/`DeployEcs` stages and every `terraform plan`/`apply` (so an infra-only change can never
  silently roll a service's image back to the module's placeholder default). Only environments
  under `infra/envs/*` are valid deploy targets.
- **Deploy health gate**: ECS updates each service to the new task definition with the
  **deployment circuit breaker enabled and `rollback = true`**
  (`infra/modules/ecs-service`) — ECS itself detects a service that can't reach steady state and
  rolls it back automatically, no external polling required. `Smoke` is the second, independent
  gate on top of that: it force-deploys, waits for `services-stable`, and only then curls
  `/health`/`/ready` through the public path — a service that's "stable" per ECS but still failing
  application-level readiness still fails the pipeline.
- **Rollback trigger**: automatic when the circuit breaker trips mid-deployment. For a bad release
  that *did* reach steady state (the failure mode the circuit breaker can't see), rollback is
  manual and explicit: `.github/workflows/rollback.yml`, dispatched with a target service and a
  previously-built SHA. It **verifies that SHA's image already exists in ECR before doing anything
  else** — refusing to "roll back" to a commit that was never actually built — then points that
  service's SSM parameters at the old `{tag, digest}` and force-deploys, reusing the exact same
  image bytes rather than rebuilding. Every run is logged in `evidence/delivery/`, per Drill 4.
- **Branch protection on `main`**: PR required, 2 approving reviews, and `validate`, `shared (Step
  4)`, `docker golden path` (`ci.yml`) plus `fmt / validate / test` (`terraform.yml`) set as
  required status checks — this ADR is the source of truth for which checks matter; a check added
  or removed here should be reflected in the ruleset in the same PR.

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
- ECR's lifecycle policy is **count-based** (`imageCountMoreThan`, keep the last N), not age-based —
  confirmed in `infra/modules/ecs-platform`, with the ADR-009 reasoning quoted directly in its
  comment: an age-only rule could expire the exact image a rollback needs.
- SSM is now load-bearing state, not just a build artifact: `terraform plan`/`apply` reads it on
  every run, so a manual `aws ecs update-service` that changes what's running **without** updating
  SSM would make Terraform's next apply silently revert the manual change. `rollback.yml` updates
  SSM for exactly this reason — it is not optional bookkeeping.
- The scan gate only fails on *fixable* findings, by design (an unfixable HIGH/CRITICAL would
  otherwise permanently block every release for a vulnerability nobody can act on yet) — but that
  means an unfixable finding needs a human to actually log it in `docs/scar-log.md`. Nothing
  currently enforces that this happens; it is a process gap, not a tooling one.
- The team must actually rehearse a rollback before grading (Drill 4), to produce the rollback-log
  evidence this ADR requires — a rollback path that's only ever been read about, not exercised,
  doesn't count as proven. `rollback.yml`'s existence makes this exercisable; the exercise itself
  is a separate, required step.

## Required proof (from brief)
Pipeline evidence + rollback log, filed under `evidence/delivery/`.
