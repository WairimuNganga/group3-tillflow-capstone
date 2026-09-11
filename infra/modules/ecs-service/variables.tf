variable "name_prefix" { type = string }
variable "service_name" { type = string }
variable "environment" { type = string }
variable "region" { type = string }
variable "account_id" { type = string }
variable "vpc_id" { type = string }
variable "vpc_cidr" { type = string }
variable "subnet_ids" { type = list(string) }
variable "cluster_arn" { type = string }
variable "execution_role_arn" { type = string }
variable "log_group_name" { type = string }
variable "kms_key_arn" { type = string }
variable "service_connect_namespace_arn" { type = string }

variable "image_repository_url" { type = string }

variable "image_tag" {
  # The "never `latest`" guard lives on the ROOT variable (envs/dev) rather
  # than here, so `terraform test` can assert that it actually fires — a
  # module-level validation is not addressable from expect_failures, which
  # would leave the rule untested. See tests/architecture.tftest.hcl.
  description = "Commit SHA. Never `latest` (ADR-009) — enforced on the root variable."
  type        = string
}

variable "image_digest" {
  description = "sha256:... — when set, the task runs the immutable digest and image_tag is metadata only."
  type        = string
  default     = null

  validation {
    condition     = var.image_digest == null || can(regex("^sha256:[0-9a-f]{64}$", var.image_digest))
    error_message = "image_digest must be a full sha256:<64 hex> digest."
  }
}

variable "adot_image" {
  description = "ADOT Collector sidecar image. Every task runs one (brief requirement)."
  type        = string
  default     = "public.ecr.aws/aws-observability/aws-otel-collector:v0.43.3"

  validation {
    condition     = !endswith(var.adot_image, ":latest")
    error_message = "Pin the ADOT sidecar — it sits in the money path's telemetry chain."
  }
}

variable "adot_config_file" {
  description = "Built-in ADOT config to run."
  type        = string
  default     = "ecs-default-config.yaml"
}

variable "amp_remote_write_url" {
  description = "Amazon Managed Prometheus remote-write endpoint (ADR-001: AMP is available in us-west-1)."
  type        = string
  default     = ""
}

variable "container_port" {
  type    = number
  default = 8080
}

variable "container_user" {
  description = "Non-root uid:gid (threat model T2.3)."
  type        = string
  default     = "10001:10001"
}

variable "health_path" {
  description = <<-EOT
    Container-level LIVENESS probe — "is this process alive". The ALB uses
    /ready instead (readiness: "can this task take traffic yet"), configured
    on the target group in the alb module. Using the same path for both would
    make a task that is up but not yet warm look healthy to the load balancer.
  EOT
  type        = string
  default     = "/health"
}

variable "cpu" {
  type    = number
  default = 512
}

variable "memory" {
  type    = number
  default = 1024
}

variable "cpu_architecture" {
  type    = string
  default = "ARM64"
}

variable "desired_count" {
  type    = number
  default = 2
}

variable "enable_execute_command" {
  description = "ECS Exec. On in dev for debugging; every session is logged to /devops-g3/ecs-exec."
  type        = bool
  default     = true
}

variable "attach_to_alb" {
  description = <<-EOT
    Whether the ALB fronts this service. An explicit boolean rather than a
    null-check on the SG id, because `count` must resolve at plan time and
    the id is unknown until apply. Workers (commission) set this false and
    have no inbound HTTP route at all.
  EOT
  type        = bool
  default     = false
}

variable "alb_security_group_id" {
  description = "Required when attach_to_alb is true."
  type        = string
  default     = null
}

variable "target_group_arn" {
  type    = string
  default = null
}

variable "peer_security_group_ids" {
  description = "caller name => SG id allowed to reach this service over Service Connect."
  type        = map(string)
  default     = {}
}

variable "allow_internet_egress" {
  description = <<-EOT
    true ONLY for services that must reach the public internet — in TillFlow
    that is `payments` (Daraja) and nothing else. See threat model T2.4/AR-7:
    this opens 443 to any host, because SGs cannot filter by hostname.
  EOT
  type        = bool
  default     = false
}

variable "environment_variables" {
  type    = map(string)
  default = {}
}

variable "secrets" {
  description = "env var name => Secrets Manager ARN. ARNs only, never values."
  type        = map(string)
  default     = {}
}

variable "readable_secret_arns" {
  description = "Secrets this task role may read. Keep it minimal (T3.1)."
  type        = list(string)
  default     = []
}

variable "sqs_send_arns" {
  type    = list(string)
  default = []
}

variable "sqs_consume_arns" {
  type    = list(string)
  default = []
}
