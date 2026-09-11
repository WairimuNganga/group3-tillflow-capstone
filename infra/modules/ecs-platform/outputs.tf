output "cluster_id" { value = aws_ecs_cluster.this.id }
output "cluster_name" { value = aws_ecs_cluster.this.name }
output "cluster_arn" { value = aws_ecs_cluster.this.arn }

output "execution_role_arn" { value = aws_iam_role.task_execution.arn }

output "service_connect_namespace_arn" {
  value = aws_service_discovery_http_namespace.this.arn
}

output "service_connect_namespace_name" {
  value = aws_service_discovery_http_namespace.this.name
}

output "ecr_repository_names" {
  description = "Config-known names (repository_url is computed) — used by the naming audit test."
  value       = { for k, r in aws_ecr_repository.service : k => r.name }
}

output "ecr_repository_urls" {
  value = { for k, r in aws_ecr_repository.service : k => r.repository_url }
}

output "log_group_names" {
  value = { for k, g in aws_cloudwatch_log_group.service : k => g.name }
}
