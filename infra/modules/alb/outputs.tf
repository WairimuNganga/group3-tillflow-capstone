output "alb_arn" { value = aws_lb.this.arn }
output "alb_dns_name" { value = aws_lb.this.dns_name }
output "security_group_id" { value = aws_security_group.this.id }
output "listener_arn" { value = aws_lb_listener.this.arn }

output "target_group_arns" {
  value = { for k, tg in aws_lb_target_group.this : k => tg.arn }
}

output "is_internal" {
  description = "Asserted by tests — must always be true (ADR-010)."
  value       = aws_lb.this.internal
}
