# Drill 3 — reconciliation DLQ → alarm → recovery

**Owner:** Minage · **Account/region:** `240462142849` / `us-west-1` · **Profile:** `group3` (SSO)

## Goal

Prove stuck reconciliation work is visible (DLQ depth), operators can follow the runbook, and recovery returns DLQ depth to zero with the CloudWatch alarm in `OK`.

## Scenario

Intentionally seed one message on `devops-g3-reconciliation-dlq` (no consumer change). CloudWatch alarm `devops-g3-reconciliation-dlq-depth` should enter `ALARM`. Recovery: purge the DLQ (drill-only poison message; production would redrive/replay per runbook).

## Timeline (UTC)

| Step | Time (UTC) | Notes |
|------|------------|--------|
| Inject message | 2026-09-22T18:13:53Z | `MessageId` `f7136341-2994-4417-ba95-b0a00d983ca5` |
| CloudWatch `ALARM` | ~2026-09-22T18:20:53Z | ~7 min after inject (SQS metric period 60s) |
| Recovery (`purge-queue`) | 2026-09-22T18:20:33Z | Runbook first action for drill poison: clear DLQ |
| CloudWatch `OK` | 2026-09-22T18:23:49Z | DLQ visible = 0 |
| **Detect → recover** | **~10 min** | Inject → OK |

## Commands (reproduce)

```bash
export AWS_PROFILE=group3
export AWS_REGION=us-west-1

DLQ_URL="https://sqs.us-west-1.amazonaws.com/240462142849/devops-g3-reconciliation-dlq"

# Break — seed DLQ
aws sqs send-message --queue-url "$DLQ_URL" \
  --message-body '{"drill":"3","purpose":"reconciliation-dlq-alert-test"}'

# Observe
aws sqs get-queue-attributes --queue-url "$DLQ_URL" \
  --attribute-names ApproximateNumberOfMessages
aws cloudwatch describe-alarms --alarm-names devops-g3-reconciliation-dlq-depth \
  --query 'MetricAlarms[0].{State:StateValue,Reason:StateReason}'

# Recover (drill message only)
aws sqs purge-queue --queue-url "$DLQ_URL"
```

## Runbook alignment

- **First safe action:** Confirm message count on `devops-g3-reconciliation-dlq`; do not redeploy payments until DLQ cause is understood ([`docs/runbook.md`](../../docs/runbook.md) § Restore and reconciliation order step 4).
- **Recovery signal:** `ApproximateNumberOfMessagesVisible` = 0 and alarm `devops-g3-reconciliation-dlq-depth` = `OK`.

## Slack / Grafana (Phase E gap)

Terraform alarm `devops-g3-reconciliation-dlq-depth` has **no SNS/Slack action** (`AlarmActions` empty). Starter Grafana → Slack rules cover payments 5xx/latency and edge probe, not DLQ depth yet.

**Still needed for full Drill 3 grading checklist:** Slack screenshot or message link when a DLQ alert is wired (Grafana rule on `payments_reconciliation_dlq_visible_messages` or CloudWatch → SNS → webhook), **or** instructor-approved CloudWatch `ALARM` console screenshot attached here.

- [ ] Slack firing evidence (Phase E follow-up)
- [x] CloudWatch alarm `ALARM` → `OK` — `drill-3-alarm-firing-20260922.json`, `drill-3-alarm-ok-20260922.json`, `drill-3-timeline-20260922.jsonl`, `drill-3-alarm-history-20260922.json`
- [x] DLQ depth back to 0

## Optional — break worker instead of seed

Scale payments to 0 or break the reconciliation consumer, drive real failures via max receive count on `devops-g3-reconciliation`, then redrive from DLQ (supported by queue redrive policy in `infra/modules/messaging`).
