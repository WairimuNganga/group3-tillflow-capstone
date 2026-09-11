variable "name_prefix" { type = string }
variable "vpc_id" { type = string }
variable "vpc_cidr" { type = string }

variable "subnet_ids" {
  description = "Private app subnets. An internal ALB never sits in a public subnet."
  type        = list(string)
}

variable "vpc_link_security_group_id" {
  description = "The only source allowed to reach this ALB (T2.1)."
  type        = string
}

variable "access_logs_bucket" {
  description = "Dedicated SSE-S3 bucket (ADR-003 exception)."
  type        = string
}

variable "listener_port" {
  description = "HTTP. TLS terminates at API Gateway; the VPC Link hop is private (T1.2)."
  type        = number
  default     = 80
}

variable "enable_deletion_protection" {
  type    = bool
  default = false
}

variable "targets" {
  description = "service name => routing + health config."
  type = map(object({
    port          = number
    health_path   = string
    priority      = number
    path_patterns = list(string)
  }))
}
