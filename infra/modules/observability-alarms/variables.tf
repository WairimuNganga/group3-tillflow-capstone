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

variable "owner_tag" {
  type    = string
  default = "minage"
}
