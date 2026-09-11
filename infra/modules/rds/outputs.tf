output "proxy_endpoint" {
  description = "What services connect to. They never address the instance directly."
  value       = aws_db_proxy.this.endpoint
}

output "instance_endpoint" {
  value = aws_db_instance.this.endpoint
}

output "instance_identifier" {
  value = aws_db_instance.this.identifier
}

output "database_name" {
  value = aws_db_instance.this.db_name
}

output "master_secret_arn" {
  description = "Secrets Manager ARN of the RDS-managed master password."
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}

output "proxy_security_group_id" {
  value = aws_security_group.proxy.id
}

output "instance_security_group_id" {
  value = aws_security_group.db.id
}
