variable "name_prefix" { type = string }
variable "account_id" { type = string }
variable "kms_key_arn" { type = string }

variable "services" {
  description = "Service names. Each gets an ECR repo and a log group."
  type        = list(string)
}

variable "service_connect_namespace" {
  description = "Cloud Map namespace for internal DNS (payments.tillflow.local)."
  type        = string
  default     = "tillflow.local"
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "ecr_image_retention_count" {
  description = "Minimum images kept per repo. Count-based so a rollback target is never aged out."
  type        = number
  default     = 20

  validation {
    condition     = var.ecr_image_retention_count >= 10
    error_message = "Keep at least 10 images — rollback needs history (ADR-009)."
  }
}

variable "secret_arns" {
  description = "Secrets the execution role may inject. Empty falls back to the name-prefixed wildcard."
  type        = list(string)
  default     = []
}
