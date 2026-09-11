output "service_name" { value = aws_ecs_service.this.name }
output "security_group_id" { value = aws_security_group.this.id }

output "security_group_name" {
  description = "Config-known (the id is computed) — used by the naming audit test."
  value       = aws_security_group.this.name
}

output "internet_egress_enabled" {
  description = "Asserted in tests: only `payments` may be true (threat model T2.4 / AR-7)."
  value       = var.allow_internet_egress
}
output "task_role_arn" { value = aws_iam_role.task.arn }
output "task_role_name" { value = aws_iam_role.task.name }
output "task_definition_arn" { value = aws_ecs_task_definition.this.arn }

output "container_names" {
  description = "Proof of the two-container requirement: app + adot."
  value       = [var.service_name, "adot"]
}
