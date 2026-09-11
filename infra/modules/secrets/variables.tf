variable "name_prefix" {
  type = string
}

variable "kms_key_arn" {
  type = string
}

variable "recovery_window_in_days" {
  description = "0 disables the soft-delete window. Keep >0 outside dev."
  type        = number
  default     = 7
}

variable "daraja_reader_role_arns" {
  description = "Only the payments task role belongs here (threat model T3.1)."
  type        = list(string)
  default     = []
}

variable "db_reader_role_arns" {
  type    = list(string)
  default = []
}

variable "slack_reader_role_arns" {
  type    = list(string)
  default = []
}
