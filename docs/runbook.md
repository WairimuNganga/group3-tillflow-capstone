# Runbook — DRI: Minage

> Per-alert first safe action, recovery signal, rollback vs roll-forward, replay ownership, backup/restore procedure, reconciliation order, RTO/RPO targets.

## G1 delivery runbook

### CodeConnection authorization

The GitHub source connection is provisioned by Terraform and authorized once in
the AWS console. Authorization grants CodePipeline access to the configured
repository source.

- AWS account: `240462142849`
- Region: `us-west-1`
- Connection: `devops-g3-github`
- Repository: `WairimuNganga/group3-tillflow-capstone`

Procedure:

1. Open AWS Console -> Developer Tools -> Settings -> Connections.
2. Open `devops-g3-github`.
3. Authorize GitHub access for `WairimuNganga/group3-tillflow-capstone`.
4. Confirm the connection status is `Available`.
5. Start a release from CodePipeline -> `devops-g3-pipeline`.

The Terraform-managed connection and pipeline are the authoritative G1 delivery
resources.

### Automated ADOT image mirror

No manual image push is required during normal deployment or a G5 rebuild.
Terraform creates the private `devops-g3/adot` ECR repository and the
`devops-g3-adot-mirror` CodeBuild project. CodePipeline runs `mirror-adot` as
the first action in `BuildScanPush`; the four service builds start only after
that action succeeds.

`mirror-adot` checks for the immutable ADOT tag in private ECR (see
`adot_image_tag` in `infra/envs/dev/main.tf`, e.g. `v0.43.3-tillflow1`):

- If the image exists, it is reused and nothing is pushed.
- Otherwise CodeBuild `docker build`s `infra/adot/Dockerfile` (upstream ADOT +
  `tillflow-collector.yaml` for AMP remote write) and pushes to private ECR.

This guarantees that ECS can pull the sidecar from private ECR before service
deployment begins.

Expected pipeline order:

```text
Source -> BuildScanPush (mirror-adot -> four service builds) -> DeployEcs -> Smoke
```

The action is visible in AWS Console under CodePipeline ->
`devops-g3-pipeline` -> `BuildScanPush` -> `mirror-adot`. Its logs are in the
`devops-g3-adot-mirror` CodeBuild project. A successful run logs either
`Reusing existing ADOT mirror` or `Building .../devops-g3/adot:<tag>`.

#### Manual recovery procedure

Use the following procedure only if the automated mirror build cannot run.
Run it after `terraform apply` has created `devops-g3/adot`. The source digest
pins the upstream multi-platform release, and `--platform` selects the ARM64
image required by the ECS task definitions. The existence check makes the
procedure safe to rerun with the immutable destination tag.

```bash
export AWS_PROFILE=tillflow-g3-lwam
export AWS_REGION=us-west-1

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
SOURCE_IMAGE="public.ecr.aws/aws-observability/aws-otel-collector@sha256:8aa9ea5f67b8d318f7d6af24677e3c70f7098bc0631147cb5fa91addbe980b06"
DESTINATION_REPOSITORY="devops-g3/adot"
DESTINATION_TAG="v0.43.3-tillflow1"
DESTINATION_IMAGE="${REGISTRY}/${DESTINATION_REPOSITORY}:${DESTINATION_TAG}"

aws ecr describe-repositories \
  --repository-names "${DESTINATION_REPOSITORY}" >/dev/null

if aws ecr describe-images \
  --repository-name "${DESTINATION_REPOSITORY}" \
  --image-ids imageTag="${DESTINATION_TAG}" >/dev/null 2>&1; then
  echo "ADOT mirror already exists: ${DESTINATION_IMAGE}"
else
  aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${REGISTRY}"

  docker build \
    --platform linux/arm64 \
    --build-arg "SOURCE_IMAGE=${SOURCE_IMAGE}" \
    -f infra/adot/Dockerfile \
    -t "${DESTINATION_IMAGE}" \
    infra/adot
  docker push "${DESTINATION_IMAGE}"
fi
```

Verify the private image and its digest:

```bash
aws ecr describe-images \
  --repository-name devops-g3/adot \
  --image-ids imageTag=v0.43.3-tillflow1 \
  --query 'imageDetails[0].{tags:imageTags,digest:imageDigest,pushedAt:imagePushedAt}' \
  --output table
```

Expected destination:

```text
240462142849.dkr.ecr.us-west-1.amazonaws.com/devops-g3/adot:v0.43.3-tillflow1
```

After manual recovery, retry the failed `mirror-adot` action or start a new
`devops-g3-pipeline` execution. Each service build writes the same private ADOT
image into its `imagedefinitions.json`, so later ECS task-definition revisions
continue using the mirror.

### G1 smoke evidence

After a release, capture evidence that the pipeline reached the end of the
golden path:

```bash
AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws codepipeline get-pipeline-state --name devops-g3-pipeline

AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws ecs describe-services \
  --cluster devops-g3 \
  --services devops-g3-web devops-g3-pos devops-g3-payments devops-g3-commission \
  --query 'services[].{service:serviceName,running:runningCount,desired:desiredCount,deployments:deployments[].rolloutState}'

AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws ecs list-tasks --cluster devops-g3 --desired-status RUNNING
```

For at least one running task, capture container health:

```bash
AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws ecs describe-tasks \
  --cluster devops-g3 \
  --tasks <task-arn> \
  --query 'tasks[].containers[].{container:name,lastStatus:lastStatus,healthStatus:healthStatus}'
```

Expected result for G1:

- pipeline stages pass through Smoke
- app container is running and healthy
- ADOT sidecar is running and healthy
- smoke stage proves `/health` and `/ready` respond through the deployed path

### Readiness follow-up

The shared health router supports dependency-aware readiness through
`ready_check`. The golden-path demo can return `/ready` without DB or Redis
checks because it is a placeholder service. When the real services replace the
demo app, `/ready` should validate required dependencies before the task is
considered ready for ALB traffic.

## G2 database bootstrap

Terraform creates a standalone database bootstrap CodeBuild project. It creates
the initial PostgreSQL service boundary, runs inside the VPC, connects through
RDS Proxy, reads the RDS-managed master secret at runtime, and stores only
service runtime credentials in `devops-g3/db`.

Run or rerun:

```bash
AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws codebuild start-build \
  --project-name devops-g3-db-bootstrap
```

Reruns are safe: existing per-service passwords are reused, so a run with
nothing to do re-asserts schemas, roles and grants and changes no credential.
To deliberately rotate, set `ROTATE_PASSWORDS=true` as a build override — every
task must then restart to pick up the new secret version.

Check the latest build:

```bash
AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws codebuild list-builds-for-project \
  --project-name devops-g3-db-bootstrap \
  --sort-order DESCENDING \
  --query 'ids[0]' \
  --output text
```

Expected database layout:

- schema owners: `tillflow_web_owner`, `tillflow_pos_owner`,
  `tillflow_payments_owner`, `tillflow_commission_owner`
- runtime roles: `tillflow_web`, `tillflow_pos`, `tillflow_payments`,
  `tillflow_commission`
- service schemas: `web`, `pos`, `payments`, `commission`
- runtime secret: `devops-g3/db`

Runtime roles do not own schemas and do not have schema `CREATE`. Migrations
should create tables through the matching owner role and grant application DML
through default privileges. A migration runner using the controlled master
credential can switch into the schema owner role for the service it is changing:

```sql
BEGIN;
SET ROLE tillflow_pos_owner;
-- apply pos schema migration here
RESET ROLE;
COMMIT;
```

Tenant tables must include:

```sql
ALTER TABLE <schema>.<table> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <schema>.<table> FORCE ROW LEVEL SECURITY;
```

This keeps application connections subject to tenant RLS policies, including
when a table owner would otherwise bypass policy checks.

## Rollback (Drill 4)

`.github/workflows/rollback.yml` is the manual rollback path ADR-009 requires.
It covers the failure mode the ECS deployment circuit breaker can't: a release
that *did* reach steady state but is behaving badly (wrong response, a bad
config value baked into the image, a bug the smoke test's `/health`+`/ready`
checks don't happen to exercise). A release that never stabilizes is already
handled automatically — the circuit breaker rolls it back on its own, nothing
to do here.

### Before you run it

Find the last-known-good commit SHA — the pipeline only ever deploys an
already-built image, and rollback is no different:

```bash
AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws ecr describe-images \
  --repository-name devops-g3/<service> \
  --query 'sort_by(imageDetails,& imagePushedAt)[-10:].{tag:imageTags[0],pushedAt:imagePushedAt}' \
  --output table
```

Or check the current, about-to-be-rolled-back-from tag:

```bash
AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws ssm get-parameter --name /devops-g3/<service>/image-tag --query Parameter.Value --output text
```

### Running it

GitHub -> Actions -> `rollback` -> Run workflow. Inputs:

- **service** -- `web` / `pos` / `payments` / `commission`
- **sha** -- the target commit SHA from above. The workflow looks this up in
  ECR before touching anything and **fails immediately** if that tag was
  never built — it will not rebuild it and will not guess.
- **reason** -- free text; goes straight into the rollback log (e.g. "Drill 4"
  or a link to the relevant `docs/scar-log.md` row).

It then: points that service's SSM image-tag/image-digest parameters at the
target, force-deploys, waits for `services-stable`, and curls the public
`/health` and `/ready` routes through the real edge (API Gateway -> VPC Link
-> ALB) before calling it done.

### After it runs

The job uploads a `rollback-log-<service>-<run id>` artifact and prints the
same block as a workflow annotation. Copy it into
`evidence/delivery/rollback-log.md` (create the file on the first rollback) —
per ADR-009, a rollback that's only ever been read about, not exercised and
logged, doesn't count as proven.

If the workflow's own health check fails after a rollback (the target image
itself doesn't come up clean either), the service is now on neither the bad
release nor a known-good one — treat that as its own incident, not a rollback
that "didn't quite work": check `aws ecs describe-services` for the deployment
state and `aws logs tail` for the task before trying a second rollback target.

## Observability alerts

**DRI:** Minage · **Webhook:** Secrets Manager `devops-g3/slack-webhook` (value never in git).

| Alert (starter) | Signal (AMP / Grafana) | First action | Recovery |
|-----------------|------------------------|--------------|----------|
| PaymentsHigh5xxRate | `sum(rate(payments_requests_total{status="5xx"}[5m])) / sum(rate(payments_requests_total[5m]))` > 0.05 for 10m | Check recent deploy; `aws logs tail` payments; consider rollback workflow | Ratio below 0.02 for 15m |
| EdgeProbeFailed | Synthetic `/health` or `/ready` failure (see `infra/scripts/reliability-edge-probe.sh`) | API Gateway stage, ALB target health, web service ECS events | Two consecutive probe successes |
| PaymentsLatencyP95 | `histogram_quantile(0.95, sum(rate(payments_request_duration_seconds_bucket[5m])) by (le))` > 2s for 15m | RDS Proxy connections, Daraja sandbox status | p95 < 1s for 15m |

Wire rules in Grafana when the ECS service is live ([infra/grafana/README.md](../infra/grafana/README.md)). Each firing alert should link to the panel URL (T8.2).
