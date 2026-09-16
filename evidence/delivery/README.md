# Evidence — Delivery / CI-CD
**DRI: Wairimu** · cross-reviews Platform

Drop here, each with **exact reproduction commands** (screenshots alone earn no credit):
- [ ] Commits / PR links for owned work
- [ ] ADR(s) for this area
- [ ] Tests (unit / integration / invariant / contract as applicable)
- [ ] Runtime proof (traces, dashboards, pipeline runs, drill recordings)
- [ ] Reproduction commands (`how-to-reproduce.md`)

## G1 delivery evidence to capture

After the ADOT health-check fix is applied and `devops-g3-pipeline` is rerun,
store the following evidence in this directory:

- [ ] CodePipeline execution showing Source, BuildScanPush, DeployEcs and Smoke passed
- [ ] CodeBuild image logs showing image build, ECR push, image scan summary and SSM image tag/digest update
- [ ] ECR scan summary showing non-fixable findings are logged and fixable HIGH/CRITICAL findings block the build
- [ ] ECS service status for `web`, `pos`, `payments` and `commission`
- [ ] ECS task container health showing both app and `adot` containers healthy
- [ ] Smoke-stage output proving deployed `/health` and `/ready` checks passed

Useful commands:

```bash
AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws codepipeline get-pipeline-state --name devops-g3-pipeline

AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws ecs describe-services \
  --cluster devops-g3 \
  --services devops-g3-web devops-g3-pos devops-g3-payments devops-g3-commission \
  --query 'services[].{service:serviceName,status:status,running:runningCount,desired:desiredCount}'

AWS_PROFILE=tillflow-g3-lwam AWS_REGION=us-west-1 \
aws ecs describe-tasks \
  --cluster devops-g3 \
  --tasks <task-arn> \
  --query 'tasks[].containers[].{container:name,lastStatus:lastStatus,healthStatus:healthStatus}'
```
