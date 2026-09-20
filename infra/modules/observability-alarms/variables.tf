variable "name_prefix" {
  type = string
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
