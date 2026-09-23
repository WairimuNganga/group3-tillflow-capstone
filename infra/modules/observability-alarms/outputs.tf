output "dlq_alarm_names" {
  value = { for k, a in aws_cloudwatch_metric_alarm.dlq_depth : k => a.alarm_name }
}

output "dlq_alarm_action_arns" {
  description = "Notification actions attached to every DLQ alarm."
  value       = distinct(flatten([for a in aws_cloudwatch_metric_alarm.dlq_depth : a.alarm_actions]))
}

output "dlq_alarms_have_slack_action" {
  description = "True only when every DLQ alarm sends both ALARM and OK to the Slack relay."
  value = alltrue([
    for a in aws_cloudwatch_metric_alarm.dlq_depth :
    contains(a.alarm_actions, aws_lambda_function.slack_alarm.arn) &&
    contains(a.ok_actions, aws_lambda_function.slack_alarm.arn)
  ])
}

output "slack_alarm_lambda_role_arn" {
  description = "Role allowed to read the Slack webhook secret at runtime."
  value       = aws_iam_role.slack_alarm.arn
}

output "slack_alarm_lambda_arn" {
  description = "Lambda action invoked by DLQ alarms for Slack delivery."
  value       = aws_lambda_function.slack_alarm.arn
}

output "canary_alarm_name" {
  value = length(aws_cloudwatch_metric_alarm.canary_success) > 0 ? aws_cloudwatch_metric_alarm.canary_success[0].alarm_name : null
}

output "ecs_alarm_names" {
  value = { for k, a in aws_cloudwatch_metric_alarm.ecs_cpu_high : k => a.alarm_name }
}

output "rds_alarm_names" {
  value = {
    cpu_high         = aws_cloudwatch_metric_alarm.rds_cpu_high.alarm_name
    connections_high = aws_cloudwatch_metric_alarm.rds_connections_high.alarm_name
  }
}
