# Starter operational alarms — DLQ visibility (G4) and synthetics success (G3).

data "archive_file" "slack_alarm" {
  type        = "zip"
  source_file = "${path.module}/slack_alarm.py"
  output_path = "${path.module}/.slack-alarm.zip"
}

data "aws_iam_policy_document" "slack_alarm_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "slack_alarm" {
  name               = "${var.name_prefix}-slack-alarm"
  assume_role_policy = data.aws_iam_policy_document.slack_alarm_assume.json

  tags = {
    Name    = "${var.name_prefix}-slack-alarm"
    service = "reliability"
    owner   = var.owner_tag
  }
}

resource "aws_cloudwatch_log_group" "slack_alarm" {
  name              = "/aws/lambda/${var.name_prefix}-slack-alarm"
  retention_in_days = var.log_retention_days

  tags = {
    Name    = "${var.name_prefix}-slack-alarm"
    service = "reliability"
    owner   = var.owner_tag
  }
}

data "aws_iam_policy_document" "slack_alarm" {
  statement {
    sid    = "WriteOwnLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.slack_alarm.arn}:*"]
  }

  statement {
    sid       = "ReadSlackWebhook"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.slack_webhook_secret_arn]
  }

  statement {
    sid       = "DecryptSlackWebhook"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "slack_alarm" {
  name   = "slack-alarm"
  role   = aws_iam_role.slack_alarm.id
  policy = data.aws_iam_policy_document.slack_alarm.json
}

resource "aws_lambda_function" "slack_alarm" {
  function_name    = "${var.name_prefix}-slack-alarm"
  role             = aws_iam_role.slack_alarm.arn
  handler          = "slack_alarm.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.slack_alarm.output_path
  source_code_hash = data.archive_file.slack_alarm.output_base64sha256
  timeout          = 10

  environment {
    variables = {
      ENVIRONMENT              = var.environment
      GRAFANA_PANEL_URL        = var.grafana_panel_url
      OWNER                    = var.owner_tag
      RUNBOOK_URL              = var.runbook_url
      SLACK_WEBHOOK_SECRET_ARN = var.slack_webhook_secret_arn
    }
  }

  tags = {
    Name    = "${var.name_prefix}-slack-alarm"
    service = "reliability"
    owner   = var.owner_tag
  }

  depends_on = [
    aws_cloudwatch_log_group.slack_alarm,
    aws_iam_role_policy.slack_alarm,
  ]
}

# CloudWatch Alarms invokes the function directly for both the red and green
# transition. Scope permission to this stack's DLQ alarms only.
resource "aws_lambda_permission" "cloudwatch_alarms" {
  statement_id   = "AllowCloudWatchDlqAlarms"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.slack_alarm.function_name
  principal      = "lambda.alarms.cloudwatch.amazonaws.com"
  source_account = var.account_id
  source_arn     = "arn:aws:cloudwatch:${var.region}:${var.account_id}:alarm:${var.name_prefix}-*-dlq-depth"
}

resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  for_each = var.dlq_names

  alarm_name          = "${var.name_prefix}-${each.key}-dlq-depth"
  alarm_description   = "Messages visible on ${each.key} DLQ — replay or fix consumer (runbook § Observability alerts)."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_lambda_function.slack_alarm.arn]
  ok_actions          = [aws_lambda_function.slack_alarm.arn]

  dimensions = {
    QueueName = each.value
  }

  tags = {
    Name    = "${var.name_prefix}-${each.key}-dlq-depth"
    service = each.key
    owner   = var.owner_tag
  }
}

resource "aws_cloudwatch_metric_alarm" "canary_success" {
  count = var.canary_alarm_enabled ? 1 : 0

  alarm_name          = "${var.name_prefix}-edge-health-canary"
  alarm_description   = "External synthetics success rate below 90% — check API Gateway, ALB, web service (runbook EdgeProbeFailed)."
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "SuccessPercent"
  namespace           = "CloudWatchSynthetics"
  period              = 60
  statistic           = "Average"
  threshold           = 90
  treat_missing_data  = "breaching"

  dimensions = {
    CanaryName = var.canary_name
  }

  tags = {
    Name    = "${var.name_prefix}-edge-health-canary"
    service = "platform"
    owner   = var.owner_tag
  }
}

resource "aws_cloudwatch_metric_alarm" "ecs_cpu_high" {
  for_each = var.ecs_service_names

  alarm_name          = "${var.name_prefix}-${each.key}-ecs-cpu-high"
  alarm_description   = "ECS CPU above 80% for ${each.key}; check recent deploy, task health and scaling."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "notBreaching"

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = each.value
  }

  tags = {
    Name    = "${var.name_prefix}-${each.key}-ecs-cpu-high"
    service = each.key
    owner   = var.owner_tag
  }
}

resource "aws_cloudwatch_metric_alarm" "rds_cpu_high" {
  alarm_name          = "${var.name_prefix}-rds-cpu-high"
  alarm_description   = "RDS CPU above 80%; check DB connections, slow queries and RDS events."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 60
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "notBreaching"

  dimensions = {
    DBInstanceIdentifier = var.rds_instance_identifier
  }

  tags = {
    Name    = "${var.name_prefix}-rds-cpu-high"
    service = "database"
    owner   = var.owner_tag
  }
}

resource "aws_cloudwatch_metric_alarm" "rds_connections_high" {
  alarm_name          = "${var.name_prefix}-rds-connections-high"
  alarm_description   = "RDS connections high for dev; check pool sizing, RDS Proxy and stuck tasks."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  metric_name         = "DatabaseConnections"
  namespace           = "AWS/RDS"
  period              = 60
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "notBreaching"

  dimensions = {
    DBInstanceIdentifier = var.rds_instance_identifier
  }

  tags = {
    Name    = "${var.name_prefix}-rds-connections-high"
    service = "database"
    owner   = var.owner_tag
  }
}
