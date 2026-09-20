output "dlq_alarm_names" {
  value = { for k, a in aws_cloudwatch_metric_alarm.dlq_depth : k => a.alarm_name }
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
