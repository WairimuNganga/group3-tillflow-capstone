output "secret_arns" {
  description = "ARNs to reference in ECS task definitions. Never the values."
  value = {
    for k, _ in local.secrets : k => try(
      aws_secretsmanager_secret.this[k].arn,
      "arn:aws:secretsmanager:*:*:secret:${var.name_prefix}/${k}*",
    )
  }
}
