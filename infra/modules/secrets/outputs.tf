output "secret_arns" {
  description = "ARNs to reference in ECS task definitions. Never the values."
  value       = { for k, s in aws_secretsmanager_secret.this : k => s.arn }
}
