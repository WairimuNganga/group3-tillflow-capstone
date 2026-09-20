# Starter operational alarms — DLQ visibility (G4) and synthetics success (G3).

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
  count = var.canary_name != null ? 1 : 0

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
