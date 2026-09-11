output "bucket_ids" {
  value = { for k, b in aws_s3_bucket.this : k => b.id }
}

output "bucket_arns" {
  value = { for k, b in aws_s3_bucket.this : k => b.arn }
}

output "alb_logs_bucket" {
  description = "Dedicated SSE-S3 bucket for ALB access logs (ADR-003 exception)."
  value       = aws_s3_bucket.this["alb-logs"].id
}
