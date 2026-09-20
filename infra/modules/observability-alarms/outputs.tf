output "dlq_alarm_names" {
  value = { for k, a in aws_cloudwatch_metric_alarm.dlq_depth : k => a.alarm_name }
}

output "canary_alarm_name" {
  value = length(aws_cloudwatch_metric_alarm.canary_success) > 0 ? aws_cloudwatch_metric_alarm.canary_success[0].alarm_name : null
}
