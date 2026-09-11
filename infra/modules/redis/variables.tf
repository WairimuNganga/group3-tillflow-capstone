variable "name_prefix" { type = string }
variable "vpc_id" { type = string }

variable "subnet_ids" {
  description = "Data-tier subnets."
  type        = list(string)
}

variable "client_security_group_ids" {
  description = "service name => SG id allowed to reach the cache."
  type        = map(string)
  default     = {}
}

variable "kms_key_arn" { type = string }

variable "engine_version" {
  type    = string
  default = "7.2"
}

variable "node_type" {
  type    = string
  default = "cache.t4g.micro"
}

variable "num_cache_clusters" {
  description = "1 in dev (cost). >1 enables automatic failover and Multi-AZ."
  type        = number
  default     = 1
}

variable "maintenance_window" {
  type    = string
  default = "sun:05:30-sun:06:30"
}

variable "snapshot_retention_limit" {
  description = "0 in dev — a cache-aside cache holds nothing that needs restoring."
  type        = number
  default     = 0
}

variable "apply_immediately" {
  type    = bool
  default = true
}
