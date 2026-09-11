provider "aws" {
  region = var.region

  # The brief requires group, owner, environment, service, managed-by and
  # capstone on every resource. The four constant ones are set here so no
  # module can forget them; `service` and `owner` are set per-resource where
  # they differ, and default_tags fills in the rest.
  default_tags {
    tags = {
      group       = var.name_prefix
      owner       = var.owner
      environment = var.environment
      service     = "platform"
      managed-by  = "terraform"
      capstone    = "tillflow"
    }
  }
}
