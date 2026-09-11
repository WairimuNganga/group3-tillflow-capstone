variable "region" {
  type    = string
  default = "us-west-1"
}

variable "name_prefix" {
  type    = string
  default = "devops-g3"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "owner" {
  description = "Default `owner` tag. Platform owns the infrastructure itself."
  type        = string
  default     = "lwam"
}

variable "kms_key_arn" {
  description = "Shared CMK from infra/bootstrap (terraform output kms_key_arn)."
  type        = string
}

# --- network ---------------------------------------------------------------

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "availability_zones" {
  description = <<-EOT
    Verified for AWS account 240462142849:
      us-west-1a us-west-1c

    Re-run this check before the first apply if the target account changes:
      aws ec2 describe-availability-zones --region us-west-1 \
        --query 'AvailabilityZones[?State==`available`].ZoneName' --output text

    The value is pinned rather than auto-discovered so plans stay reproducible.
  EOT
  type        = list(string)
  default     = ["us-west-1a", "us-west-1c"]

  validation {
    condition     = length(var.availability_zones) == 2 && length(distinct(var.availability_zones)) == 2
    error_message = "Exactly two distinct AZs (ADR-001). us-west-1 may not offer a third to this account."
  }
}

variable "nat_gateway_count" {
  description = "1 in dev (AR-1). Set to 2 before any drill claiming AZ-independent egress."
  type        = number
  default     = 1
}

# --- edge ------------------------------------------------------------------

variable "api_throttle_burst" {
  type    = number
  default = 200
}

variable "api_throttle_rate" {
  type    = number
  default = 100
}

# --- compute ---------------------------------------------------------------

variable "image_tags" {
  description = <<-EOT
    Commit SHA per service. `REPLACE_ME` is the pre-first-deploy placeholder —
    the pipeline overrides it. Never `latest` (ADR-009).
  EOT
  type        = map(string)
  default = {
    web        = "REPLACE_ME"
    pos        = "REPLACE_ME"
    payments   = "REPLACE_ME"
    commission = "REPLACE_ME"
  }

  validation {
    condition     = alltrue([for tag in values(var.image_tags) : tag != "latest"])
    error_message = "`latest` is never a valid tag — build by commit SHA, deploy the immutable digest (ADR-009)."
  }
}

variable "image_digests" {
  description = "Immutable digests, set by the pipeline. Take precedence over image_tags."
  type        = map(string)
  default     = {}
}

variable "desired_counts" {
  type = map(number)
  default = {
    web        = 2
    pos        = 2
    payments   = 2
    commission = 1
  }
}

variable "task_sizes" {
  type = map(object({ cpu = number, memory = number }))
  default = {
    web        = { cpu = 512, memory = 1024 }
    pos        = { cpu = 512, memory = 1024 }
    payments   = { cpu = 1024, memory = 2048 }
    commission = { cpu = 512, memory = 1024 }
  }
}

variable "amp_remote_write_url" {
  description = "Amazon Managed Prometheus remote-write endpoint (ADR-001)."
  type        = string
  default     = ""
}

variable "mpesa_adapter" {
  description = <<-EOT
    Which M-Pesa adapter a deployed environment runs. `fake` is for CI and k6
    only — a deployed environment running `fake` would settle every sale
    instantly with no money moving (threat model T6.7), so it is rejected here.
  EOT
  type        = string
  default     = "sandbox"

  validation {
    condition     = var.mpesa_adapter == "sandbox"
    error_message = "A deployed environment must use the sandbox adapter. `fake` belongs to CI/k6 only (T6.7)."
  }
}

variable "log_retention_days" {
  type    = number
  default = 30
}

# --- data ------------------------------------------------------------------

variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "db_multi_az" {
  description = "false in dev (AR-2). Must be true before any G4 resilience claim."
  type        = bool
  default     = false
}

variable "db_backup_retention_days" {
  type    = number
  default = 7
}

variable "db_deletion_protection" {
  description = "false in dev so G5's destroy/rebuild proof can actually run."
  type        = bool
  default     = false
}

variable "db_skip_final_snapshot" {
  type    = bool
  default = true
}

variable "cache_node_type" {
  type    = string
  default = "cache.t4g.micro"
}

variable "cache_num_clusters" {
  type    = number
  default = 1
}

# --- secrets ---------------------------------------------------------------

variable "secret_recovery_window_days" {
  type    = number
  default = 7
}
