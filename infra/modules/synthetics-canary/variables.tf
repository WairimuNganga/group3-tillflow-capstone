variable "name_prefix" {
  type = string
}

variable "region" {
  type = string
}

variable "account_id" {
  type = string
}

variable "api_base_url" {
  description = "Public API Gateway stage URL (trailing slash optional)."
  type        = string
}

variable "kms_key_arn" {
  description = "CMK for the dedicated synthetics artifacts bucket (ADR-003)."
  type        = string
}

variable "schedule_expression" {
  description = "EventBridge rate for external probe (brief: 1 minute)."
  type        = string
  default     = "rate(1 minute)"
}

variable "owner_tag" {
  type    = string
  default = "lwam"
}
