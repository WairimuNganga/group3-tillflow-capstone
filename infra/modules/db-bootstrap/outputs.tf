output "project_name" {
  description = "Run this CodeBuild project to create G2 DB schemas, runtime roles and service credentials."
  value       = aws_codebuild_project.this.name
}

output "role_arn" {
  description = "IAM role used by the database bootstrap job."
  value       = aws_iam_role.this.arn
}

output "project_arn" {
  description = "ARN of the project, so the pipeline role can StartBuild on it."
  value       = aws_codebuild_project.this.arn
}
