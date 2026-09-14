output "pipeline_name" {
  value = aws_codepipeline.this.name
}

output "github_connection_arn" {
  description = "Authorize this pending GitHub connection once in the AWS console before the first run."
  value       = aws_codestarconnections_connection.github.arn
}

output "codebuild_project_names" {
  value = merge(
    { for k, p in aws_codebuild_project.image : k => p.name },
    { smoke = aws_codebuild_project.smoke.name },
  )
}
