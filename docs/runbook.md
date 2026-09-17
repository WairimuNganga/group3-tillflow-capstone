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

`mirror-adot` checks for immutable tag `v0.43.3` in private ECR:

- If the image exists, it is reused and nothing is pushed.
- If the repository is empty after a rebuild, CodeBuild pulls the pinned ARM64
  ADOT image from public ECR and pushes it into the private repository.

This guarantees that ECS can pull the sidecar from private ECR before service
deployment begins.

Expected pipeline order:

```text
Source -> BuildScanPush (mirror-adot -> four service builds) -> DeployEcs -> Smoke
```

The action is visible in AWS Console under CodePipeline ->
`devops-g3-pipeline` -> `BuildScanPush` -> `mirror-adot`. Its logs are in the
`devops-g3-adot-mirror` CodeBuild project. A successful run logs either
`Reusing existing ADOT mirror` or `Mirroring ... to .../devops-g3/adot:v0.43.3`.

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
DESTINATION_TAG="v0.43.3"
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

  docker pull --platform linux/arm64 "${SOURCE_IMAGE}"
  docker tag "${SOURCE_IMAGE}" "${DESTINATION_IMAGE}"
  docker push "${DESTINATION_IMAGE}"
fi
```

Verify the private image and its digest:

```bash
aws ecr describe-images \
  --repository-name devops-g3/adot \
  --image-ids imageTag=v0.43.3 \
  --query 'imageDetails[0].{tags:imageTags,digest:imageDigest,pushedAt:imagePushedAt}' \
  --output table
```

Expected destination:

```text
240462142849.dkr.ecr.us-west-1.amazonaws.com/devops-g3/adot:v0.43.3
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
