provider "aws" {
  region = var.region

  # Every resource in this stack carries the tags the brief requires. `owner`
  # and `service` are set per-resource where they differ; the rest are constant.
  default_tags {
    tags = {
      group       = var.name_prefix
      owner       = var.owner
      environment = "shared"
      service     = "platform"
      managed-by  = "terraform"
      capstone    = "tillflow"
    }
  }
}
