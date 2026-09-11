variable "name_prefix" {
  type = string
}

variable "account_id" {
  description = "Appended to bucket names — S3 names are globally unique."
  type        = string
}

variable "kms_key_arn" {
  description = "Shared CMK from bootstrap. Not used by the alb-logs bucket (ADR-003 exception)."
  type        = string
}
