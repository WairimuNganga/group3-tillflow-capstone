output "queue_urls" {
  value = { for k, q in aws_sqs_queue.main : k => q.id }
}

output "queue_arns" {
  value = { for k, q in aws_sqs_queue.main : k => q.arn }
}

output "dlq_arns" {
  value = { for k, q in aws_sqs_queue.dlq : k => q.arn }
}

output "dlq_names" {
  description = "For the DLQ-depth alarm — stuck work must be visible (ADR-004)."
  value       = { for k, q in aws_sqs_queue.dlq : k => q.name }
}
