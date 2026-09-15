variable "name_prefix" { type = string }
variable "region" { type = string }
variable "account_id" { type = string }
variable "github_repository" { type = string }
variable "github_branch" { type = string }
variable "artifact_bucket" { type = string }
variable "artifact_bucket_arn" { type = string }
variable "kms_key_arn" { type = string }
variable "services" { type = list(string) }
variable "cluster_name" { type = string }
variable "api_endpoint" { type = string }
variable "desired_counts" { type = map(number) }

variable "db_bootstrap_project_name" {
  description = <<-EOT
    CodeBuild project that creates the PostgreSQL schemas, owner/runtime role
    pairs and the devops-g3/db secret value. Runs as a pipeline stage before
    DeployEcs, because ECS cannot start a task while that secret has no version.
  EOT
  type        = string
}

variable "db_bootstrap_project_arn" {
  description = "ARN of the same project, so the pipeline role can StartBuild on it."
  type        = string
}

variable "codebuild_image" {
  description = "ARM64 CodeBuild image so Docker builds match ECS Fargate ARM64 tasks."
  type        = string
  default     = "aws/codebuild/amazonlinux-aarch64-standard:3.0"
}
