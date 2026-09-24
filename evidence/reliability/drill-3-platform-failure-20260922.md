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

At the time of the first 2026-09-22 run, Terraform alarm `devops-g3-reconciliation-dlq-depth` had **no SNS/Slack action** (`AlarmActions` empty). Starter Grafana → Slack rules covered payments 5xx/latency and edge probe, not DLQ depth yet.

**Original gap:** the first drill proved CloudWatch `ALARM` → `OK`, but the DLQ alarm was not yet wired to Slack.

- [x] Slack firing evidence (Phase E follow-up) — closed by the 2026-09-23 UTC / 2026-09-24 EAT retest below.
- [x] CloudWatch alarm `ALARM` → `OK` — `drill-3-alarm-firing-20260922.json`, `drill-3-alarm-ok-20260922.json`, `drill-3-timeline-20260922.jsonl`, `drill-3-alarm-history-20260922.json`
- [x] DLQ depth back to 0

## Retest attempt — 2026-09-23

The reconciliation DLQ was seeded again and CloudWatch moved from `ALARM` back
to `OK`:

- Inject: [`drill-3-inject-20260923.json`](./drill-3-inject-20260923.json)
- Recovery alarm capture without Slack actions: [`drill-3-alarm-recovered-20260923.json`](./drill-3-alarm-recovered-20260923.json)
- Recovery timestamp: [`drill-3-recovered-at-20260923.txt`](./drill-3-recovered-at-20260923.txt)

This did **not** close the Slack gap. The recovery alarm capture still showed
`AlarmActions: []` and `OKActions: []`, so the Terraform-managed Slack relay was
not live when this drill ran. The drill was re-run after the DLQ alarms showed
the Lambda ARN in both action lists.

## Successful Slack retest — 2026-09-23 UTC / 2026-09-24 EAT

After applying the Terraform-managed Slack relay, both DLQ alarms showed the
Lambda ARN in `AlarmActions` and `OKActions`. The reconciliation DLQ was seeded
again with one drill message and then recovered by deleting that drill message.

- Inject: [`drill-3-inject-20260923.json`](./drill-3-inject-20260923.json)
- Firing alarm capture: [`drill-3-slack-alarm-firing-20260923.json`](./drill-3-slack-alarm-firing-20260923.json)
- Recovery alarm capture: [`drill-3-slack-alarm-recovered-20260923.json`](./drill-3-slack-alarm-recovered-20260923.json)
- Recovery timestamp: [`drill-3-recovered-at-20260923.txt`](./drill-3-recovered-at-20260923.txt)
- Slack firing screenshot: [`phase-f/screenshots/slack-dlq-firing-20260924.png`](./phase-f/screenshots/slack-dlq-firing-20260924.png)
- Slack recovery screenshot: [`phase-f/screenshots/slack-dlq-recovery-20260924.png`](./phase-f/screenshots/slack-dlq-recovery-20260924.png)

Result: Drill 3 now proves CloudWatch DLQ alarm firing, Slack notification with
the full alert contract, safe recovery to `OK`, and Slack recovery notification.

## Optional — break worker instead of seed

Scale payments to 0 or break the reconciliation consumer, drive real failures via max receive count on `devops-g3-reconciliation`, then redrive from DLQ (supported by queue redrive policy in `infra/modules/messaging`).
