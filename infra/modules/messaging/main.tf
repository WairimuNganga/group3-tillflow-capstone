# SQS queues + DLQs and the EventBridge daily-close schedule.
#
# The DLQ is not decoration: threat model M2/M4 and ADR-004 both depend on
# stuck work being *visible* (DLQ depth) rather than silently dropped, and the
# G4 drill replays from it.

locals {
  queues = {
    # Payments reconciliation: retries of Daraja status queries for payments
    # stuck in `pending` (ADR-004).
    reconciliation = {
      visibility_timeout_seconds = 300
      max_receive_count          = 5
    }
    # Commission payout requests, one message per attendant payout so a
    # mid-batch failure resumes per-attendant rather than per-batch (M11).
    payout = {
      visibility_timeout_seconds = 300
      max_receive_count          = 3
    }
  }
}

resource "aws_sqs_queue" "dlq" {
  for_each = local.queues

  name                      = "${var.name_prefix}-${each.key}-dlq"
  kms_master_key_id         = var.kms_key_arn
  message_retention_seconds = 1209600 # 14d — the full window to notice and replay

  tags = { Name = "${var.name_prefix}-${each.key}-dlq" }
}

resource "aws_sqs_queue" "main" {
  for_each = local.queues

  name                       = "${var.name_prefix}-${each.key}"
  kms_master_key_id          = var.kms_key_arn
  visibility_timeout_seconds = each.value.visibility_timeout_seconds
  message_retention_seconds  = 345600 # 4d

  # Long polling: fewer empty receives, lower cost, faster delivery than the
  # 20s-of-nothing that short polling produces.
  receive_wait_time_seconds = 20

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[each.key].arn
    maxReceiveCount     = each.value.max_receive_count
  })

  tags = { Name = "${var.name_prefix}-${each.key}" }
}

# Allow the DLQ to be redriven back to its source queue — this is what makes
# the G4 DLQ-recovery drill a supported operation rather than a manual re-post.
resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  for_each = local.queues

  queue_url = aws_sqs_queue.dlq[each.key].id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.main[each.key].arn]
  })
}

# ---------------------------------------------------------------------------
# Daily close schedule
#
# EventBridge Scheduler (not a classic rule) because it supports a real
# timezone. The commission SLO is stated in EAT, and expressing the schedule in
# EAT rather than hand-converting to UTC removes the whole class of bug in
# threat model M14.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.name_prefix}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.main["payout"].arn]
  }
  statement {
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "enqueue-daily-close"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

resource "aws_scheduler_schedule" "daily_close" {
  name        = "${var.name_prefix}-daily-close"
  description = "Triggers the commission daily close. SLO: terminal by 06:30 EAT."
  group_name  = "default"

  flexible_time_window {
    mode = "OFF" # a payout window is not flexible
  }

  schedule_expression          = var.daily_close_cron
  schedule_expression_timezone = var.daily_close_timezone

  target {
    arn      = aws_sqs_queue.main["payout"].arn
    role_arn = aws_iam_role.scheduler.arn

    # The period is resolved by the worker from this trigger time, once, and
    # carried through the run — never re-derived from now() mid-calculation,
    # or a re-run computes a different period (M14).
    input = jsonencode({
      event = "commission.daily_close.requested"
    })
  }
}
