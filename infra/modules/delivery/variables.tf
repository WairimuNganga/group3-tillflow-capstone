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
variable "adot_repository_name" { type = string }
variable "adot_source_image" { type = string }
variable "adot_image_tag" { type = string }

variable "codebuild_image" {
  description = "ARM64 CodeBuild image so Docker builds match ECS Fargate ARM64 tasks."
  type        = string
  default     = "aws/codebuild/amazonlinux-aarch64-standard:3.0"
}
