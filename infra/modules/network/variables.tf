variable "name_prefix" {
  description = "Resource name prefix (devops-g3)."
  type        = string
}

variable "region" {
  description = "AWS region, used to build VPC endpoint service names."
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR. /16 leaves room for the /20 tier split."
  type        = string
  default     = "10.20.0.0/16"

  validation {
    condition     = tonumber(split("/", var.vpc_cidr)[1]) <= 20
    error_message = "vpc_cidr must be /20 or larger to fit three subnet tiers across two AZs."
  }
}

variable "availability_zones" {
  description = <<-EOT
    Exactly two AZs, pinned explicitly (ADR-001). NOT auto-discovered: AZ
    availability differs per account, and an auto-discovered list makes plans
    non-reproducible between teammates.

    VERIFY BEFORE FIRST APPLY:
      aws ec2 describe-availability-zones --region us-west-1 \
        --query 'AvailabilityZones[?State==`available`].ZoneName'
  EOT
  type        = list(string)

  validation {
    condition     = length(var.availability_zones) == 2
    error_message = "Exactly two AZs — the brief requires two, and us-west-1 may not offer a third."
  }
}

variable "nat_gateway_count" {
  description = <<-EOT
    1 for dev (AR-1: accepted single point of egress failure, on cost grounds).
    Set to 2 before any drill that claims AZ-independent egress.
  EOT
  type        = number
  default     = 1

  validation {
    condition     = var.nat_gateway_count >= 1 && var.nat_gateway_count <= 2
    error_message = "nat_gateway_count must be 1 (dev) or 2 (one per AZ)."
  }
}

variable "interface_endpoints" {
  description = "AWS services reachable without traversing NAT (threat model T2.4)."
  type        = list(string)
  default = [
    "ecr.api",
    "ecr.dkr",
    "secretsmanager",
    "logs",
    "monitoring",
    "ssm",
    "ssmmessages", # ECS Exec
    "sqs",
    "kms",
  ]
}

variable "flow_log_retention_days" {
  description = "CloudWatch retention for VPC flow logs."
  type        = number
  default     = 30
}

variable "kms_key_arn" {
  description = "CMK for the flow-log group."
  type        = string
}
