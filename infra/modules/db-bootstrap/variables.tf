variable "name_prefix" { type = string }
variable "region" { type = string }
variable "account_id" { type = string }
variable "vpc_id" { type = string }

variable "subnet_ids" {
  description = "Private app subnets where the bootstrap job can reach RDS Proxy and AWS APIs."
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group used by the database bootstrap CodeBuild job."
  type        = string
}

variable "db_host" {
  description = "RDS Proxy endpoint used by service runtimes and the bootstrap job."
  type        = string
}

variable "db_name" {
  description = "Application database name."
  type        = string
}

variable "master_secret_arn" {
  description = "RDS-managed master secret ARN. Read only by the bootstrap job."
  type        = string
}

variable "db_secret_arn" {
  description = "Application DB secret ARN populated by the bootstrap job."
  type        = string
}

variable "kms_key_arn" {
  description = "Shared CMK used for Secrets Manager and logs."
  type        = string
}

variable "services" {
  description = "Service schemas and runtime DB roles to create."
  type        = list(string)
}

variable "codebuild_image" {
  description = "Standard Linux image used to run psql and AWS CLI for DB bootstrap."
  type        = string
  default     = "aws/codebuild/standard:7.0"
}
