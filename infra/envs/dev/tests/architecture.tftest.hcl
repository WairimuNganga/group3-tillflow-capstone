# Structural architecture rules, verified with a mocked AWS provider — no
# credentials, no cost, runs on every PR.
#
# These are the contracts the design must not silently lose. Each assertion
# names the ADR or threat-model row it defends, so a failure says *why* it
# matters, not just that a value changed.
#
#   cd infra/envs/dev && terraform test

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "240462142849"
    }
  }

  # Policy documents are computed locally but mock to "" by default, which
  # fails JSON validation on assume_role_policy.
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

variables {
  kms_key_arn = "arn:aws:kms:us-west-1:240462142849:key/11111111-2222-3333-4444-555555555555"
}

run "architecture_contracts" {
  # plan, not apply: assertions are on config literals and variable-derived
  # values, which are plan-deterministic. Mock-generated IDs would not pass
  # AWS ARN format validation on apply.
  command = plan

  # --- Networking (ADR-010) ----------------------------------------------

  assert {
    condition     = module.alb.is_internal == true
    error_message = "ALB must be internal. A public ALB bypasses API Gateway's authn and throttling (ADR-010, threat model T2.1)."
  }

  assert {
    condition     = length(var.availability_zones) == 2
    error_message = "Exactly two AZs — the brief requires two, and us-west-1 may not offer a third (ADR-001)."
  }

  assert {
    condition     = alltrue([for az in var.availability_zones : startswith(az, var.region)])
    error_message = "Every AZ must be in the configured region."
  }

  assert {
    condition     = length(distinct(var.availability_zones)) == 2
    error_message = "The two AZs must be distinct — two subnets in one AZ is not multi-AZ."
  }

  # --- Egress posture (threat model T2.4 / AR-7) --------------------------

  assert {
    condition = length(distinct([
      for svc in ["web", "pos", "payments", "commission"] : module.service[svc].security_group_name
    ])) == 4
    error_message = "Each service needs its own SG. A shared app-tier SG defeats per-service isolation (ADR-010)."
  }

  # The single most important line in this file. If a future change gives
  # pos/web/commission an internet route, the exfiltration surface widens
  # silently and AR-7's compensating controls stop holding.
  assert {
    condition = [
      for svc in ["web", "pos", "payments", "commission"] :
      svc if module.service[svc].internet_egress_enabled
    ] == ["payments"]
    error_message = "Only `payments` may reach the internet — it is the only service that talks to Daraja (threat model T2.4 / AR-7)."
  }

  # --- Artifact identity (ADR-009) ----------------------------------------

  assert {
    condition     = alltrue([for svc, tag in var.image_tags : tag != "latest"])
    error_message = "`latest` is never a valid tag. Build by commit SHA, deploy the immutable digest (ADR-009, T7.3)."
  }

  assert {
    condition     = length(var.image_tags) == 4
    error_message = "Every service needs an explicit image tag — a missing one silently defaults."
  }

  # --- Two containers per task (brief requirement) ------------------------

  assert {
    condition = alltrue([
      for svc in ["web", "pos", "payments", "commission"] :
      length(module.service[svc].container_names) == 2 && contains(module.service[svc].container_names, "adot")
    ])
    error_message = "Every backend task runs the application PLUS an ADOT collector sidecar."
  }

  # --- Adapter safety (threat model T6.7) ---------------------------------

  assert {
    condition     = var.mpesa_adapter == "sandbox"
    error_message = "A deployed environment must never run the fake adapter — every sale would settle with no money moving (T6.7)."
  }

  # --- Naming (the brief's naming rule, audited at G1) --------------------

  assert {
    condition     = can(regex("^devops-g[0-9]+$", var.name_prefix))
    error_message = "name_prefix must be devops-g<N>, lowercase and hyphenated."
  }

  assert {
    condition     = module.ecs_platform.cluster_name == var.name_prefix
    error_message = "ECS cluster is named for the group, per the brief's naming table."
  }

  assert {
    condition = alltrue([
      for svc, name in module.ecs_platform.ecr_repository_names :
      name == "${var.name_prefix}/${svc}"
    ])
    error_message = "ECR repos use the slash form from the brief: devops-g3/<service>."
  }

  assert {
    condition = alltrue([
      for svc, name in module.ecs_platform.log_group_names :
      name == "/${var.name_prefix}/${svc}"
    ])
    error_message = "Log groups follow /devops-g3/<service>, per the brief's naming table."
  }

  # --- Data durability (ADR-002) ------------------------------------------

  assert {
    condition     = var.db_backup_retention_days >= 7
    error_message = "Backup retention must cover the stated RPO with margin (ADR-002)."
  }
}

# ---------------------------------------------------------------------------
# Guards on the risks we accepted rather than fixed. These fail loudly if
# someone changes an accepted risk without updating the threat model.
# ---------------------------------------------------------------------------

run "accepted_risk_guards" {
  command = plan

  variables {
    kms_key_arn = "arn:aws:kms:us-west-1:240462142849:key/11111111-2222-3333-4444-555555555555"
  }

  assert {
    condition     = var.nat_gateway_count == 1 || var.nat_gateway_count == 2
    error_message = "nat_gateway_count is 1 (AR-1, accepted) or 2 (one per AZ). Anything else is unintended."
  }

  assert {
    condition     = var.db_multi_az == false || var.db_multi_az == true
    error_message = "db_multi_az must be explicit. AR-2 accepts single-AZ in dev only; G4 requires true."
  }
}

# ---------------------------------------------------------------------------
# Input validation — cheap, catches the mistakes people actually make.
# ---------------------------------------------------------------------------

run "rejects_latest_tag" {
  command = plan

  variables {
    kms_key_arn = "arn:aws:kms:us-west-1:240462142849:key/11111111-2222-3333-4444-555555555555"
    image_tags = {
      web        = "latest"
      pos        = "a1b2c3d"
      payments   = "a1b2c3d"
      commission = "a1b2c3d"
    }
  }

  expect_failures = [var.image_tags]
}

run "rejects_three_azs" {
  command = plan

  variables {
    kms_key_arn        = "arn:aws:kms:us-west-1:240462142849:key/11111111-2222-3333-4444-555555555555"
    availability_zones = ["us-west-1a", "us-west-1b", "us-west-1c"]
  }

  expect_failures = [var.availability_zones]
}

run "rejects_fake_adapter_in_deployed_env" {
  command = plan

  variables {
    kms_key_arn   = "arn:aws:kms:us-west-1:240462142849:key/11111111-2222-3333-4444-555555555555"
    mpesa_adapter = "fake"
  }

  expect_failures = [var.mpesa_adapter]
}
