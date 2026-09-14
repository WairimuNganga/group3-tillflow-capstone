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
