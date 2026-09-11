variable "name_prefix" { type = string }
variable "vpc_id" { type = string }
variable "vpc_cidr" { type = string }

variable "subnet_ids" {
  description = "Private app subnets for the VPC Link ENIs."
  type        = list(string)
}

variable "vpc_link_security_group_id" {
  description = "Created by the root module to break the ALB <-> VPC Link dependency cycle."
  type        = string
}

variable "alb_listener_arn" { type = string }
variable "kms_key_arn" { type = string }

variable "stage_name" {
  type    = string
  default = "v1"
}

variable "throttle_burst" {
  description = "Per-route burst. First line of defence for T1.3."
  type        = number
  default     = 200
}

variable "throttle_rate" {
  type    = number
  default = 100
}

variable "integration_timeout_ms" {
  description = "Must stay under the Payments SLO's 60s callback budget."
  type        = number
  default     = 29000

  validation {
    condition     = var.integration_timeout_ms > 0 && var.integration_timeout_ms <= 30000
    error_message = "HTTP API integration timeout must be 1-30000 ms."
  }
}

variable "cors_allow_origins" {
  type    = list(string)
  default = ["*"]
}

variable "log_retention_days" {
  type    = number
  default = 30
}
