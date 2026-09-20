# Structural architecture rules, verified with a mocked AWS provider — no
# credentials, no cost, runs on every PR.
#
# These are the contracts the design must not silently lose. Each assertion
# names the ADR or threat-model row it defends, so a failure says *why* it
# matters, not just that a value changed.
#
#   cd infra/envs/dev && terraform test

mock_provider "aws" {
  override_during = plan

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

  mock_resource "aws_prometheus_workspace" {
    override_during = plan

    defaults = {
      id                  = "ws-C6DCB907-F2D7-4D96-957B-66691F865D8B"
      arn                 = "arn:aws:aps:us-west-1:240462142849:workspace/ws-C6DCB907-F2D7-4D96-957B-66691F865D8B"
      prometheus_endpoint = "https://aps-workspaces.us-west-1.amazonaws.com/workspaces/ws-C6DCB907-F2D7-4D96-957B-66691F865D8B/"
    }
  }

  mock_resource "aws_synthetics_canary" {
    override_during = plan

    defaults = {
      name = "devops-g3-edge-health"
      arn  = "arn:aws:synthetics:us-west-1:240462142849:canary:devops-g3-edge-health"
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

  assert {
    condition     = module.delivery.codebuild_project_names["adot-mirror"] == "${var.name_prefix}-adot-mirror"
    error_message = "The delivery lane must provision the ADOT mirror build so a fresh private ECR repository can boot ECS tasks."
  }

  # --- Schema migrations run before deploy (G2) ----------------------------
  #
  # A task started against a stale schema fails at request time, not deploy
  # time — Payments returned 500 UndefinedTableError for exactly this reason
  # while only POS migrations were wired into the pipeline.
  assert {
    condition = alltrue([
      for svc in ["pos", "payments", "commission"] :
      module.delivery.codebuild_project_names["${svc}-migrations"] == "${var.name_prefix}-${svc}-migrations"
    ])
    error_message = "POS, Payments and Commission must each have an Alembic migration build in the delivery lane, run before DeployEcs."
  }

  # --- ADOT can actually publish traces (Phase F) -------------------------
  #
  # The telemetry statement was once a single grant scoped to the AMP workspace
  # ARN. Only aps:RemoteWrite accepts that ARN, so live ADOT logs showed
  # `xray:PutTraceSegments AccessDenied` and no trace ever reached X-Ray. The
  # failure is invisible in a plan diff, hence this assertion.
  assert {
    condition = alltrue([
      for svc in ["web", "pos", "payments", "commission"] : alltrue([
        for st in module.service[svc].telemetry_statements :
        st.resources == ["*"]
        if length(setintersection(
          toset(st.actions), toset(module.service[svc].resourceless_telemetry_actions)
        )) > 0
      ])
    ])
    error_message = "X-Ray actions must be granted on \"*\". AWS rejects resource-level permissions for PutTraceSegments/PutTelemetryRecords, so scoping them (e.g. to the AMP workspace ARN) yields AccessDenied at runtime."
  }

  # The converse: "*" must not leak to the one action that can be scoped.
  assert {
    condition = alltrue([
      for svc in ["web", "pos", "payments", "commission"] : alltrue([
        for st in module.service[svc].telemetry_statements :
        st.resources == [module.amp.workspace_arn]
        if contains(st.actions, "aps:RemoteWrite")
      ])
    ])
    error_message = "aps:RemoteWrite must stay scoped to the AMP workspace ARN — it is the one telemetry action that supports resource-level permissions."
  }

  # --- ADOT can reach its backends without internet egress (AR-7) ---------
  #
  # Correct IAM is not enough. Only `payments` may reach the internet, so the
  # other three sidecars need PrivateLink to export at all -- live logs showed
  # `context deadline exceeded` against xray.<region>.amazonaws.com (web, pos)
  # and the AMP remote-write endpoint (web, pos, commission) while IAM was
  # perfectly valid. The alternative fix -- granting them internet egress --
  # would breach AR-7, so this assertion pins the private route.
  assert {
    condition = alltrue([
      for svc in ["xray", "aps-workspaces"] :
      contains(module.network.interface_endpoint_services, svc)
    ])
    error_message = "VPC interface endpoints for xray and aps-workspaces are required: web/pos/commission have no internet egress (AR-7), so without them the mandatory ADOT sidecar cannot publish traces or metrics."
  }

  # --- Web talks to commission (daily close / payouts) ---------------------
  #
  # web/deps.py only builds HttpCommissionClient when COMMISSION_BASE_URL is
  # set; without the SG rule the env var turns a "not configured" page into a
  # timeout. Both halves or neither.
  # The SG ids themselves are unknown until apply, so this asserts the ports
  # and the description literal; which groups it joins is fixed in config.
  assert {
    condition = (
      aws_vpc_security_group_ingress_rule.web_to_commission.from_port == 8080 &&
      aws_vpc_security_group_ingress_rule.web_to_commission.to_port == 8080 &&
      aws_vpc_security_group_ingress_rule.web_to_commission.ip_protocol == "tcp" &&
      aws_vpc_security_group_ingress_rule.web_to_commission.description == "Service Connect: web to commission"
    )
    error_message = "Web must reach commission on 8080/tcp over Service Connect, or the daily close and payout screens cannot load."
  }

  # --- Two containers per task (brief requirement) ------------------------

  assert {
    condition = alltrue([
      for svc in ["web", "pos", "payments", "commission"] :
      length(module.service[svc].container_names) == 2 && contains(module.service[svc].container_names, "adot")
    ])
    error_message = "Every backend task runs the application PLUS an ADOT collector sidecar."
  }

  # --- Metrics backend (ADR-001 / ADR-008) ---------------------------------

  assert {
    condition     = module.amp.workspace_id != null && module.amp.workspace_id != ""
    error_message = "AMP workspace must be Terraform-managed — ADOT remote write must not rely on a console-only workspace."
  }

  assert {
    condition     = coalesce(var.amp_remote_write_url, module.amp.remote_write_url) != ""
    error_message = "ADOT sidecars need a non-empty remote-write URL from module.amp (or an explicit override)."
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

  # --- External probe (G3) -------------------------------------------------

  assert {
    condition     = module.synthetics_canary.canary_name == "${var.name_prefix}-edge-health"
    error_message = "A 1-minute external synthetics canary must probe the public edge (G3 blocked-if)."
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
