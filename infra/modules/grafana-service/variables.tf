variable "name_prefix" { type = string }
variable "environment" { type = string }
variable "region" { type = string }
variable "account_id" { type = string }

variable "vpc_id" { type = string }
variable "vpc_cidr" { type = string }
variable "subnet_ids" { type = list(string) }

variable "cluster_arn" { type = string }
variable "execution_role_arn" { type = string }
variable "kms_key_arn" { type = string }

variable "alb_security_group_id" { type = string }
variable "target_group_arn" { type = string }

variable "image" { type = string }

variable "amp_prometheus_endpoint" { type = string }
variable "amp_workspace_arn" { type = string }

variable "grafana_root_url" {
  description = "Public URL including subpath, e.g. https://api.example/v1/grafana/"
  type        = string
}

variable "admin_password_secret_arn" { type = string }

variable "slack_webhook_secret_arn" {
  description = "devops-g3/slack-webhook — plain-string incoming webhook URL for alerting."
  type        = string
}

variable "readable_secret_arns" {
  type    = list(string)
  default = []
}

variable "log_retention_days" { type = number }

variable "desired_count" {
  type    = number
  default = 1
}

variable "cpu" {
  type    = number
  default = 512
}

variable "memory" {
  type    = number
  default = 1024
}

variable "enable_execute_command" {
  type    = bool
  default = true
}
