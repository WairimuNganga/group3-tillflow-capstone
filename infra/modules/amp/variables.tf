variable "name_prefix" {
  type        = string
  description = "Group prefix, e.g. devops-g3."
}

variable "alias" {
  type        = string
  description = "Human-readable AMP workspace alias."
  default     = null
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Extra tags merged with module defaults."
}
