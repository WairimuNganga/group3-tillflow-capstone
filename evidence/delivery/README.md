# Evidence — Delivery / CI-CD
**DRI: Wairimu** · cross-reviews Platform

Drop here, each with **exact reproduction commands** (screenshots alone earn no credit):
- [ ] Commits / PR links for owned work
- [ ] ADR(s) for this area
- [ ] Tests (unit / integration / invariant / contract as applicable)
- [ ] Runtime proof (traces, dashboards, pipeline runs, drill recordings)
- [ ] Reproduction commands (`how-to-reproduce.md`)

## G1 delivery evidence to capture

### Current status

Latest verified delivery state.

Passed:

- [x] Source stage reads `main` through the approved GitHub CodeConnection.
- [x] BuildScanPush runs for all four services: `web`, `pos`, `payments` and `commission`.
- [x] Service image builds push to private ECR and write image tag/digest values to SSM.
- [x] ECR scan gate logs HIGH/CRITICAL findings and only blocks fixable HIGH/CRITICAL findings.

Pending:

- [ ] DeployEcs final rerun after the ADOT sidecar image source change is merged/applied.
- [ ] Smoke stage after DeployEcs reaches steady state.
- [ ] ECS proof that both the app container and `adot` sidecar are healthy.
- [ ] HTTP proof that deployed `/health` and `/ready` return success.

Current DeployEcs blocker:

Private ECS tasks timed out pulling that public image, so DeployEcs did not reach
steady state. The fix is to use the mirrored private ECR image instead:

After the ADOT health-check fix is applied and `devops-g3-pipeline` is rerun,
store the evidence:

- [ ] CodePipeline execution showing Source, BuildScanPush, DeployEcs and Smoke passed
- [ ] CodeBuild image logs showing image build, ECR push, image scan summary and SSM image tag/digest update
- [ ] ECR scan summary showing non-fixable findings are logged and fixable HIGH/CRITICAL findings block the build
- [ ] ECS service status for `web`, `pos`, `payments` and `commission`
- [ ] ECS task container health showing both app and `adot` containers healthy
- [ ] Smoke-stage output proving deployed `/health` and `/ready` checks passed

