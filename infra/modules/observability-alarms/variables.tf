variable "name_prefix" {
  type = string
}

variable "region" {
  description = "AWS region containing the alarms and notification Lambda."
  type        = string
}

variable "account_id" {
  description = "AWS account ID used to scope CloudWatch's Lambda invocation permission."
  type        = string
}

variable "environment" {
  description = "Environment label included in every Slack notification."
  type        = string
}

variable "slack_webhook_secret_arn" {
  description = "Secrets Manager ARN containing the Slack incoming webhook URL."
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key used by the Slack webhook secret."
  type        = string
}

variable "grafana_panel_url" {
  description = "Grafana dashboard URL included in actionable alerts."
  type        = string
}

variable "runbook_url" {
  description = "Runbook URL included in actionable alerts."
  type        = string
}

variable "log_retention_days" {
  description = "Retention for the Slack alarm relay Lambda log group."
  type        = number
  default     = 30
}

variable "dlq_names" {
  description = "Map of queue key → DLQ name (from messaging module)."
  type        = map(string)
}

variable "canary_name" {
  description = "CloudWatch Synthetics canary name; omit to skip canary alarm."
  type        = string
  default     = null
}

variable "canary_alarm_enabled" {
  description = "Create the synthetics alarm. Separate from canary_name so count is plan-time known."
  type        = bool
  default     = false
}

variable "ecs_cluster_name" {
  description = "ECS cluster name for service health alarms."
  type        = string
}

variable "ecs_service_names" {
  description = "Map of service key -> ECS service name."
  type        = map(string)
  default     = {}
}

variable "rds_instance_identifier" {
  description = "RDS DB instance identifier for database health alarms."
  type        = string
}

variable "owner_tag" {
  type    = string
  default = "minage"
}
