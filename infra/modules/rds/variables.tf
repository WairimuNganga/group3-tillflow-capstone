variable "name_prefix" { type = string }
variable "region" { type = string }
variable "vpc_id" { type = string }

variable "subnet_ids" {
  description = "Data-tier subnets — no NAT/IGW route (ADR-010)."
  type        = list(string)
}

variable "client_security_group_ids" {
  description = "service name => SG id. Only these may reach the proxy."
  type        = map(string)
  default     = {}
}

variable "kms_key_arn" { type = string }

variable "engine_version" {
  type    = string
  default = "16.4"
}

variable "instance_class" {
  description = "db.t4g.medium for dev (ADR-002). Upgrade path documented before load drills."
  type        = string
  default     = "db.t4g.medium"
}

variable "allocated_storage" {
  type    = number
  default = 20
}

variable "max_allocated_storage" {
  description = "Storage autoscaling ceiling."
  type        = number
  default     = 100
}

variable "database_name" {
  type    = string
  default = "tillflow"
}

variable "master_username" {
  type    = string
  default = "tillflow_admin"
}

variable "multi_az" {
  description = "false in dev (AR-2, cost). Must be true before any G4 drill claiming AZ resilience."
  type        = bool
  default     = false
}

variable "backup_retention_days" {
  description = "7d in dev. PITR within this window satisfies RPO <= 24h with margin (ADR-002)."
  type        = number
  default     = 7

  validation {
    condition     = var.backup_retention_days >= 1
    error_message = "Backups must be enabled — RPO depends on them."
  }
}

variable "backup_window" {
  type    = string
  default = "03:00-04:00"
}

variable "maintenance_window" {
  type    = string
  default = "sun:04:30-sun:05:30"
}

variable "deletion_protection" {
  type    = bool
  default = true
}

variable "skip_final_snapshot" {
  description = "true only in dev, where G5 requires a working destroy/rebuild."
  type        = bool
  default     = false
}

variable "performance_insights_enabled" {
  type    = bool
  default = true
}

variable "statement_timeout_ms" {
  description = "Kill a runaway query rather than let it starve the shared instance (T4.6)."
  type        = string
  default     = "30000"
}

variable "idle_in_transaction_timeout_ms" {
  type    = string
  default = "60000"
}

variable "proxy_max_connections_percent" {
  type    = number
  default = 75
}

variable "proxy_max_idle_connections_percent" {
  type    = number
  default = 50
}
