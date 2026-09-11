variable "region" {
  description = "AWS region. Assigned by the program; see ADR-001."
  type        = string
  default     = "us-west-1"
}

variable "name_prefix" {
  description = "Prefix on every nameable resource, per the brief's naming rule."
  type        = string
  default     = "devops-g3"

  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.name_prefix))
    error_message = "name_prefix must be lowercase alphanumeric with hyphens."
  }
}

variable "owner" {
  description = "Value of the required `owner` tag for resources in this stack."
  type        = string
  default     = "lwam"
}

variable "github_repository" {
  description = "owner/repo that the CI deploy role trusts via OIDC."
  type        = string
  default     = "WairimuNganga/group3-tillflow-capstone"

  validation {
    condition     = can(regex("^[^/]+/[^/]+$", var.github_repository))
    error_message = "github_repository must be in owner/repo form."
  }
}

variable "ci_allowed_refs" {
  description = <<-EOT
    Git refs allowed to assume the CI deploy role. Deliberately main-only:
    a PR branch can run `terraform plan` with a read-only role, but only main
    may apply (ADR-009). Widening this list widens who can deploy.
  EOT
  type        = list(string)
  default     = ["ref:refs/heads/main"]
}
