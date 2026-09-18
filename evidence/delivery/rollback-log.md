# Rollback log — Drill 4

**DRI: Wairimu** · [ADR-009](../../docs/adr/ADR-009-ci-cd-promotion-and-rollback.md) required proof

Both attempts are recorded here, not just the clean one — the first attempt is what actually
proved a real rollback path needs to be exercised end to end, not just read about. Reproduce with
the exact commands under each section (screenshots alone earn no credit).

## Summary

| | Attempt 1 | Attempt 2 |
|---|---|---|
| Run | [`35385291854`](https://github.com/WairimuNganga/group3-tillflow-capstone/actions/runs/35385291854) | [`35387343229`](https://github.com/WairimuNganga/group3-tillflow-capstone/actions/runs/35387343229) |
| Service | `web` | `web` |
| From → To | `b54b84a` → `b9eabd8` | `b54b84a` → `b9eabd8` |
| Workflow's own report | ✅ success | ✅ success |
| Actually running the target image? | ❌ **no** | ✅ **yes**, verified independently |

Attempt 1 exposed a real bug in `rollback.yml`: `--force-new-deployment` alone restarts tasks on
the service's *current* task definition, and ECS never resolves a container's image from SSM at
deploy time — so the workflow updated SSM, reported success, and the running container never
actually changed. Fixed in [PR #36](https://github.com/WairimuNganga/group3-tillflow-capstone/pull/36)
by registering a new task definition revision with the target image, the same way CodePipeline's
own ECS deploy action does it. Attempt 2 re-ran the drill against the fix and is independently
verified below, not just trusted from the workflow's own success report.

## Attempt 1 — reported success, silently did nothing

- **When**: 2026-09-18T19:25:22Z
- **From**: `b54b84abcfc0efc726c1e3a1694c787988de90b2`
- **To (intended)**: `b9eabd8a935c2326b9a91a1a1c5077380cefbdfe`
  (`sha256:56d4d05ee15c0916adb42a9f6be214bd182e07cfe4502f11748c3cf197cbac2f`)
- **Reason**: Drill 4 — G4 rollback rehearsal
- **Run**: [`35385291854`](https://github.com/WairimuNganga/group3-tillflow-capstone/actions/runs/35385291854), all steps green

Every reported signal said success — SSM updated, `aws ecs describe-services` showed
`rolloutState: COMPLETED`, `curl .../health` returned 200. Checking the *actual* running task
directly told a different story:

```bash
TASK_ARN=$(aws ecs list-tasks --cluster devops-g3 --service-name devops-g3-web \
  --query 'taskArns[0]' --output text)
aws ecs describe-tasks --cluster devops-g3 --tasks "$TASK_ARN" \
  --query "tasks[0].containers[?name=='web'].image | [0]" --output text
```

Observed:

```text
240462142849.dkr.ecr.us-west-1.amazonaws.com/devops-g3/web:b54b84abcfc0efc726c1e3a1694c787988de90b2
```

Still the pre-rollback image. Confirmed the root cause directly against the task definition ECS
was actually using:

```bash
aws ecs describe-task-definition --task-definition devops-g3-web:34 \
  --query 'taskDefinition.containerDefinitions[?name==`web`].image' --output text
```

```text
240462142849.dkr.ecr.us-west-1.amazonaws.com/devops-g3/web:b54b84abcfc0efc726c1e3a1694c787988de90b2
```

The task definition itself — a literal string, not something ECS re-resolves from SSM — still
pointed at the old image. `--force-new-deployment` had simply recycled tasks onto the same
definition.

## Fix

[PR #36](https://github.com/WairimuNganga/group3-tillflow-capstone/pull/36),
merged [`958fe06`](https://github.com/WairimuNganga/group3-tillflow-capstone/commit/958fe06e59666daafa00fc688bb34d55ca73502d).
`rollback.yml` now describes the current task definition, swaps only the target container's image
to the verified digest, registers that as a new revision, and deploys the service to it explicitly
— mirroring what CodePipeline's ECS deploy action already does with `imagedefinitions.json`. Also
added a post-deploy check that inspects the running task's actual container image and fails the
workflow if it doesn't match the target, so this class of silent no-op can't report success again.

## Attempt 2 — re-run against the fix, verified independently

- **When**: 2026-09-18T19:39:57Z (approx, per run duration)
- **From**: `b54b84abcfc0efc726c1e3a1694c787988de90b2`
- **To**: `b9eabd8a935c2326b9a91a1a1c5077380cefbdfe`
  (`sha256:56d4d05ee15c0916adb42a9f6be214bd182e07cfe4502f11748c3cf197cbac2f`)
- **Reason**: Drill 4 — G4 rollback rehearsal (retry after fixing task-definition bug)
- **Triggered by**: @WairimuNganga
- **Outcome**: success
- **Run**: [`35387343229`](https://github.com/WairimuNganga/group3-tillflow-capstone/actions/runs/35387343229)

This time, independently re-checked exactly as attempt 1 was — not trusting the workflow's own
report:

```bash
aws ssm get-parameter --name /devops-g3/web/image-tag --query 'Parameter.Value' --output text

TASK_ARN=$(aws ecs list-tasks --cluster devops-g3 --service-name devops-g3-web \
  --query 'taskArns[0]' --output text)
aws ecs describe-tasks --cluster devops-g3 --tasks "$TASK_ARN" \
  --query "tasks[0].containers[?name=='web'].image | [0]" --output text

curl -sS https://w6m0ja1aic.execute-api.us-west-1.amazonaws.com/v1/health
```

Observed:

```text
b9eabd8a935c2326b9a91a1a1c5077380cefbdfe

240462142849.dkr.ecr.us-west-1.amazonaws.com/devops-g3/web@sha256:56d4d05ee15c0916adb42a9f6be214bd182e07cfe4502f11748c3cf197cbac2f

{"status":"ok","service":"web","git_sha":"5cfa264cfe0fd22aee1bc8983020f60cac697ce7"}
```

SSM matches the target SHA, and — the part that actually matters — the running container's image
digest (`sha256:56d4d05e...`) is a genuinely different digest from what was running before
(`sha256:84a7adc8592b696a771381e9dceea852546c8231db946c655ff5559a8b54d3f7`, attempt 1's pre-rollback
image). The rollback demonstrably changed what's deployed this time.

### Known, separate discrepancy — not a rollback.yml defect

`/health`'s `git_sha` field reads `5cfa264...`, not `b9eabd8...`, even though the ECR tag is
correctly `b9eabd8`. This means the images tagged `b9eabd8` and an earlier `5cfa264` share the same
underlying digest — almost certainly `buildspecs/service-image.yml`'s "image already exists, skip
rebuild" reuse logic, applied to `web`, which has no application code of its own yet and so
produces byte-identical layers across many commits. The `GIT_COMMIT_SHA` build-arg baked at image
build time didn't get refreshed when the tag was reused. This is a pre-existing gap in the shared
build/reuse path, not something this rollback mechanism causes or is responsible for fixing —
flagged here since it means `/health`'s `git_sha` isn't a fully reliable artifact-identity check
for a service without its own Dockerfile yet. The ECR **tag** and **digest** (what `rollback.yml`
and `terraform plan`/`apply` actually key off) are unaffected and correct.
