variable "name_prefix" {
  type = string
}

variable "account_id" {
  type = string
}

variable "kms_key_arn" {
  type = string
}

variable "daily_close_cron" {
  description = "When the daily close fires. Runs early enough to be terminal by the 06:30 EAT SLO."
  type        = string
  default     = "cron(0 5 * * ? *)"
}

variable "daily_close_timezone" {
  description = "IANA timezone. EAT so the schedule matches the SLO's stated timezone (M14)."
  type        = string
  default     = "Africa/Nairobi"
}
