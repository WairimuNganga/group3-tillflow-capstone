# TillFlow dev environment.
#
#   internet → API Gateway → VPC Link → internal ALB → ECS Fargate (private)
#                                                        ├─ web
#                                                        ├─ pos
#                                                        ├─ payments   ← internet egress (Daraja)
#                                                        ├─ grafana    ← internet egress (AMP query)
#                                                        └─ commission
#                                                             ↓
#                                    RDS Proxy → PostgreSQL · Valkey · SQS+DLQ
#
# Every task runs two containers: the application plus an ADOT sidecar.

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  services = ["web", "pos", "payments", "commission"]

  # Bump when infra/adot/tillflow-collector.yaml changes (immutable ECR tag).
  adot_image_tag = "v0.43.3-tillflow4"

  grafana_version   = "11.4.0"
  grafana_image_tag = "11.4.0-tillflow3"
  # Pin the upstream multi-platform manifest; the mirror build selects the
  # ARM64 child image required by the Fargate task definitions.
  adot_source_image = "public.ecr.aws/aws-observability/aws-otel-collector@sha256:8aa9ea5f67b8d318f7d6af24677e3c70f7098bc0631147cb5fa91addbe980b06"

  # Which services the ALB fronts. `commission` is a worker driven by
  # EventBridge → SQS; it has no inbound HTTP route at all, which is also why
  # it cannot be reached from outside to trigger a payout.
  http_services = ["web", "pos", "payments"]

  # First infra apply creates ECR repositories before any service image exists.
  # Keep services at zero tasks while they still point at the placeholder image;
  # once the delivery pipeline writes a real tag or digest, Terraform can scale
  # to the normal desired count without waiting for a second manual edit.
  service_desired_counts = {
    for service in local.services : service =>
    var.image_tags[service] == "REPLACE_ME" && lookup(var.image_digests, service, null) == null
    ? 0
    : var.desired_counts[service]
  }
}

# ---------------------------------------------------------------------------
# Foundations
# ---------------------------------------------------------------------------

module "network" {
  source = "../../modules/network"

  name_prefix        = var.name_prefix
  region             = var.region
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
  nat_gateway_count  = var.nat_gateway_count
  kms_key_arn        = var.kms_key_arn
}

module "storage" {
  source = "../../modules/s3"

  name_prefix = var.name_prefix
  account_id  = local.account_id
  region      = var.region
  kms_key_arn = var.kms_key_arn
}

# Secret CONTAINERS only — no resource policies here. The policies name the
# task roles allowed to read each secret, and those roles are created by
# modules that consume these secret ARNs. Referencing them from inside this
# module would be a dependency cycle (Terraform builds its graph from config
# references, so a conditional does not help). The policies are attached as
# root-level resources further down, which depends on both sides without
# either module depending on the other.
module "secrets" {
  source = "../../modules/secrets"

  name_prefix             = var.name_prefix
  kms_key_arn             = var.kms_key_arn
  recovery_window_in_days = var.secret_recovery_window_days
  db_proxy_services       = local.services
}

# G2 database bootstrap runner. The job runs inside the VPC, reaches RDS through
# the proxy, and writes per-service credentials to devops-g3/db. Terraform owns
# the runner and permissions; generated passwords stay out of Terraform state.
resource "aws_security_group" "db_bootstrap" {
  name        = "${var.name_prefix}-db-bootstrap"
  description = "G2 DB bootstrap job"
  vpc_id      = module.network.vpc_id

  tags = {
    Name    = "${var.name_prefix}-db-bootstrap"
    service = "platform"
  }
}

resource "aws_vpc_security_group_egress_rule" "db_bootstrap_in_vpc" {
  security_group_id = aws_security_group.db_bootstrap.id
  description       = "In-VPC access for RDS Proxy and VPC endpoints"
  cidr_ipv4         = module.network.vpc_cidr
  ip_protocol       = "-1"
}

resource "aws_vpc_security_group_egress_rule" "db_bootstrap_https" {
  security_group_id = aws_security_group.db_bootstrap.id
  description       = "HTTPS for package repositories and AWS APIs"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

# ---------------------------------------------------------------------------
# Edge
#
# The VPC Link SG lives here rather than in either module, because the ALB
# needs it as ingress and API Gateway needs the ALB's listener — a cycle if
# either module owned it.
# ---------------------------------------------------------------------------

resource "aws_security_group" "vpc_link" {
  name        = "${var.name_prefix}-vpclink"
  description = "API Gateway VPC Link ENIs"
  vpc_id      = module.network.vpc_id

  tags = { Name = "${var.name_prefix}-vpclink" }
}

resource "aws_vpc_security_group_egress_rule" "vpc_link_to_alb" {
  security_group_id = aws_security_group.vpc_link.id
  description       = "To the internal ALB"
  cidr_ipv4         = module.network.vpc_cidr
  ip_protocol       = "-1"
}

module "alb" {
  source = "../../modules/alb"

  name_prefix                = var.name_prefix
  vpc_id                     = module.network.vpc_id
  vpc_cidr                   = module.network.vpc_cidr
  subnet_ids                 = module.network.private_app_subnet_ids
  vpc_link_security_group_id = aws_security_group.vpc_link.id
  access_logs_bucket         = module.storage.alb_logs_bucket

  # ALB creation performs an access-log delivery preflight. Wait for the S3
  # bucket policy from the storage module first, otherwise a fresh apply can
  # fail intermittently with "Access Denied for bucket".
  depends_on = [module.storage]

  targets = {
    web = {
      port          = 8080
      health_path   = "/ready"
      priority      = 300
      path_patterns = ["/*"]
    }
    pos = {
      port          = 8080
      health_path   = "/ready"
      priority      = 100
      path_patterns = ["/api/pos/*"]
    }
    payments = {
      port          = 8080
      health_path   = "/ready"
      priority      = 200
      path_patterns = ["/api/payments/*", "/callback/*"]
    }
    grafana = {
      port = 3000
      # Subpath URL /grafana/api/health returns 301; ALB hits the task directly on :3000.
      health_path = "/api/health"
      priority    = 280
      # APIGW prepends /v1 so paths match GF_SERVER_ROOT_URL .../v1/grafana/
      path_patterns = ["/v1/grafana", "/v1/grafana/*"]
    }
  }

  # POS exposes internal settlement endpoints for payments only. Public API
  # Gateway traffic reaches this listener first, so reject those paths before
  # the broader /api/pos/* rule can forward them.
  blocked_path_patterns = {
    pos_internal = {
      priority      = 50
      path_patterns = ["/api/pos/internal/*"]
    }
  }
}

module "apigw" {
  source = "../../modules/apigw"

  name_prefix                = var.name_prefix
  vpc_id                     = module.network.vpc_id
  vpc_cidr                   = module.network.vpc_cidr
  subnet_ids                 = module.network.private_app_subnet_ids
  vpc_link_security_group_id = aws_security_group.vpc_link.id
  alb_listener_arn           = module.alb.listener_arn
  kms_key_arn                = var.kms_key_arn
  throttle_burst             = var.api_throttle_burst
  throttle_rate              = var.api_throttle_rate
}

# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------

module "ecs_platform" {
  source = "../../modules/ecs-platform"

  name_prefix        = var.name_prefix
  account_id         = local.account_id
  kms_key_arn        = var.kms_key_arn
  services           = local.services
  log_retention_days = var.log_retention_days
  secret_arns        = values(module.secrets.secret_arns)
}

# Private mirror of the ADOT sidecar. ECS tasks run in private subnets and pull
# service images through ECR VPC endpoints; pulling the sidecar from public ECR
# can time out before the task starts. Keep the sidecar in our account so every
# container image comes from private ECR.
resource "aws_ecr_repository" "adot" {
  name                 = "${var.name_prefix}/adot"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = var.kms_key_arn
  }

  tags = {
    Name    = "${var.name_prefix}-adot"
    service = "telemetry"
  }
}

resource "aws_ecr_lifecycle_policy" "adot" {
  repository = aws_ecr_repository.adot.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 30 ADOT images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 30
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_ecr_repository" "grafana" {
  name                 = "${var.name_prefix}/grafana"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = var.kms_key_arn
  }

  tags = {
    Name    = "${var.name_prefix}-grafana"
    service = "grafana"
  }
}

resource "aws_ecr_lifecycle_policy" "grafana" {
  repository = aws_ecr_repository.grafana.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 15 Grafana images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 15
      }
      action = { type = "expire" }
    }]
  })
}

module "service" {
  source   = "../../modules/ecs-service"
  for_each = toset(local.services)

  name_prefix  = var.name_prefix
  service_name = each.key
  environment  = var.environment
  region       = var.region
  account_id   = local.account_id

  vpc_id     = module.network.vpc_id
  vpc_cidr   = module.network.vpc_cidr
  subnet_ids = module.network.private_app_subnet_ids

  cluster_arn                   = module.ecs_platform.cluster_arn
  execution_role_arn            = module.ecs_platform.execution_role_arn
  log_group_name                = module.ecs_platform.log_group_names[each.key]
  service_connect_namespace_arn = module.ecs_platform.service_connect_namespace_arn
  kms_key_arn                   = var.kms_key_arn

  image_repository_url = module.ecs_platform.ecr_repository_urls[each.key]
  image_tag            = var.image_tags[each.key]
  image_digest         = lookup(var.image_digests, each.key, null)
  adot_image           = "${aws_ecr_repository.adot.repository_url}:${local.adot_image_tag}"
  amp_remote_write_url = coalesce(var.amp_remote_write_url, module.amp.remote_write_url)
  amp_workspace_arn    = module.amp.workspace_arn

  # Only HTTP services sit behind the ALB. commission is a worker driven by
  # EventBridge → SQS and is deliberately unreachable over HTTP from outside.
  attach_to_alb         = contains(local.http_services, each.key)
  alb_security_group_id = contains(local.http_services, each.key) ? module.alb.security_group_id : null
  target_group_arn      = contains(local.http_services, each.key) ? module.alb.target_group_arns[each.key] : null

  # THE control from threat model T2.4 / AR-7: only payments talks to Daraja,
  # so only payments gets a route off the VPC. The other three cannot reach
  # the internet at all.
  allow_internet_egress = each.key == "payments"

  desired_count = local.service_desired_counts[each.key]
  cpu           = var.task_sizes[each.key].cpu
  memory        = var.task_sizes[each.key].memory

  environment_variables = merge(
    {
      DB_HOST    = module.rds.proxy_endpoint
      DB_NAME    = module.rds.database_name
      REDIS_HOST = module.redis.primary_endpoint
      REDIS_PORT = tostring(module.redis.port)
      DB_SCHEMA  = each.key
      # Hard-wired per environment, never a runtime flag reachable from a
      # request path (ADR-007, threat model T6.7).
      MPESA_ADAPTER = var.mpesa_adapter
    },
    each.key == "payments" ? {
      RECONCILIATION_QUEUE_URL = module.messaging.queue_urls["reconciliation"]
      PAYOUT_QUEUE_URL         = module.messaging.queue_urls["payout"]
      POS_BASE_URL             = "http://pos:8080"
    } : {},
    each.key == "pos" ? {
      PAYMENTS_BASE_URL = "http://payments:8080"
    } : {},
    each.key == "commission" ? {
      PAYOUT_QUEUE_URL  = module.messaging.queue_urls["payout"]
      PAYMENTS_BASE_URL = "http://payments:8080"
    } : {},
  )

  # Secret ARNs injected as env vars at task start. Values never touch state.
  #
  # DB credentials come from the `devops-g3/db` secret, which holds one JSON
  # key per service. The `:<key>::` suffix is the ECS json-key selector, so
  # `pos` receives only the `pos` credentials and cannot read `payments`'.
  # That keeps ADR-002's one-least-privilege-role-per-service intact instead
  # of handing every task a single shared login.
  secrets = merge(
    {
      DB_CREDENTIALS = "${module.secrets.secret_arns["db"]}:${each.key}::"
    },
    each.key == "payments" ? {
      # Payments reads Daraja settings as flat environment variables. The
      # secret remains one JSON document in Secrets Manager; ECS selects each
      # key at task start so the values never pass through Terraform state.
      DARAJA_CONSUMER_KEY        = "${module.secrets.secret_arns["daraja"]}:DARAJA_CONSUMER_KEY::"
      DARAJA_CONSUMER_SECRET     = "${module.secrets.secret_arns["daraja"]}:DARAJA_CONSUMER_SECRET::"
      DARAJA_PASSKEY             = "${module.secrets.secret_arns["daraja"]}:DARAJA_PASSKEY::"
      DARAJA_SHORTCODE           = "${module.secrets.secret_arns["daraja"]}:DARAJA_SHORTCODE::"
      DARAJA_INITIATOR           = "${module.secrets.secret_arns["daraja"]}:DARAJA_INITIATOR::"
      DARAJA_SECURITY_CREDENTIAL = "${module.secrets.secret_arns["daraja"]}:DARAJA_SECURITY_CREDENTIAL::"
      MPESA_CALLBACK_SECRET      = "${module.secrets.secret_arns["daraja"]}:MPESA_CALLBACK_SECRET::"
    } : {},
  )

  # Every service reads the DB secret; only payments additionally reads Daraja.
  # That second half is what makes "commission never calls Daraja directly" a
  # permission boundary rather than a promise (threat model T3.1 — the brief
  # blocks G2 on exactly this).
  readable_secret_arns = concat(
    [module.secrets.secret_arns["db"]],
    each.key == "payments" ? [module.secrets.secret_arns["daraja"]] : [],
  )

  sqs_send_arns = each.key == "commission" ? [module.messaging.queue_arns["payout"]] : (
    each.key == "payments" ? [module.messaging.queue_arns["reconciliation"]] : []
  )

  sqs_consume_arns = each.key == "payments" ? [
    module.messaging.queue_arns["reconciliation"],
    module.messaging.queue_arns["payout"],
  ] : []
}

# commission → payments over Service Connect, never through the ALB (T3.2).
resource "aws_vpc_security_group_ingress_rule" "commission_to_payments" {
  security_group_id            = module.service["payments"].security_group_id
  description                  = "Service Connect: commission to payments B2C endpoint"
  referenced_security_group_id = module.service["commission"].security_group_id
  from_port                    = 8080
  to_port                      = 8080
  ip_protocol                  = "tcp"
}

# POS creates sales and calls payments to start/observe STK flows.
resource "aws_vpc_security_group_ingress_rule" "pos_to_payments" {
  security_group_id            = module.service["payments"].security_group_id
  description                  = "Service Connect: pos to payments"
  referenced_security_group_id = module.service["pos"].security_group_id
  from_port                    = 8080
  to_port                      = 8080
  ip_protocol                  = "tcp"
}

# Payments calls POS internal settlement endpoints after callback/reconciliation.
resource "aws_vpc_security_group_ingress_rule" "payments_to_pos" {
  security_group_id            = module.service["pos"].security_group_id
  description                  = "Service Connect: payments to pos internal settlement"
  referenced_security_group_id = module.service["payments"].security_group_id
  from_port                    = 8080
  to_port                      = 8080
  ip_protocol                  = "tcp"
}

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

module "rds" {
  source = "../../modules/rds"

  name_prefix = var.name_prefix
  region      = var.region
  vpc_id      = module.network.vpc_id
  subnet_ids  = module.network.private_data_subnet_ids
  kms_key_arn = var.kms_key_arn
  proxy_auth_secret_arns = [
    for service in local.services : module.secrets.secret_arns["db-proxy-${service}"]
  ]

  client_security_group_ids = merge(
    { for s in local.services : s => module.service[s].security_group_id },
    { db-bootstrap = aws_security_group.db_bootstrap.id },
  )

  instance_class        = var.db_instance_class
  multi_az              = var.db_multi_az
  backup_retention_days = var.db_backup_retention_days
  deletion_protection   = var.db_deletion_protection
  skip_final_snapshot   = var.db_skip_final_snapshot
}

module "redis" {
  source = "../../modules/redis"

  name_prefix = var.name_prefix
  vpc_id      = module.network.vpc_id
  subnet_ids  = module.network.private_data_subnet_ids
  kms_key_arn = var.kms_key_arn

  client_security_group_ids = { for s in local.services : s => module.service[s].security_group_id }

  node_type          = var.cache_node_type
  num_cache_clusters = var.cache_num_clusters
}

# Metrics backend for ADOT remote write and Grafana (ADR-001 / ADR-008).
module "amp" {
  source = "../../modules/amp"

  name_prefix = var.name_prefix
  alias       = var.amp_workspace_alias
}

module "grafana" {
  source = "../../modules/grafana-service"

  name_prefix = var.name_prefix
  environment = var.environment
  region      = var.region
  account_id  = local.account_id

  vpc_id     = module.network.vpc_id
  vpc_cidr   = module.network.vpc_cidr
  subnet_ids = module.network.private_app_subnet_ids

  cluster_arn        = module.ecs_platform.cluster_arn
  execution_role_arn = module.ecs_platform.execution_role_arn
  kms_key_arn        = var.kms_key_arn

  alb_security_group_id = module.alb.security_group_id
  target_group_arn      = module.alb.target_group_arns["grafana"]

  image = "${aws_ecr_repository.grafana.repository_url}:${local.grafana_image_tag}"

  amp_prometheus_endpoint = module.amp.prometheus_endpoint
  amp_workspace_arn       = module.amp.workspace_arn

  grafana_root_url = "${trimsuffix(module.apigw.api_endpoint, "/")}/grafana/"

  admin_password_secret_arn = module.secrets.secret_arns["grafana-admin"]
  slack_webhook_secret_arn  = module.secrets.secret_arns["slack-webhook"]
  readable_secret_arns = [
    module.secrets.secret_arns["grafana-admin"],
    module.secrets.secret_arns["slack-webhook"],
  ]

  log_retention_days = var.log_retention_days
  desired_count      = 1
}

module "messaging" {
  source = "../../modules/messaging"

  name_prefix = var.name_prefix
  account_id  = local.account_id
  kms_key_arn = var.kms_key_arn
}

# G3 external probe — 1-minute synthetics against public /health and /ready.
module "synthetics_canary" {
  source = "../../modules/synthetics-canary"

  name_prefix  = var.name_prefix
  region       = var.region
  account_id   = local.account_id
  api_base_url = module.apigw.api_endpoint
  kms_key_arn  = var.kms_key_arn
}

module "observability_alarms" {
  source = "../../modules/observability-alarms"

  name_prefix             = var.name_prefix
  dlq_names               = module.messaging.dlq_names
  canary_name             = module.synthetics_canary.canary_name
  canary_alarm_enabled    = true
  ecs_cluster_name        = module.ecs_platform.cluster_name
  ecs_service_names       = { for service in local.services : service => module.service[service].service_name }
  rds_instance_identifier = module.rds.instance_identifier
}

module "db_bootstrap" {
  source = "../../modules/db-bootstrap"

  name_prefix       = var.name_prefix
  region            = var.region
  account_id        = local.account_id
  vpc_id            = module.network.vpc_id
  subnet_ids        = module.network.private_app_subnet_ids
  security_group_id = aws_security_group.db_bootstrap.id

  db_host           = module.rds.proxy_endpoint
  db_name           = module.rds.database_name
  master_secret_arn = module.rds.master_secret_arn
  db_secret_arn     = module.secrets.secret_arns["db"]
  db_proxy_secret_arns = {
    for service in local.services : service => module.secrets.secret_arns["db-proxy-${service}"]
  }
  kms_key_arn = var.kms_key_arn
  services    = local.services
}

# ---------------------------------------------------------------------------
# Delivery
#
# AWS-native lane required by the brief: CodeConnection -> CodePipeline ->
# CodeBuild -> ECR -> ECS -> post-deploy smoke. GitHub Actions remains the PR
# check and Terraform plan/apply lane; application releases flow through this
# Terraform-managed pipeline.
# ---------------------------------------------------------------------------

module "delivery" {
  source = "../../modules/delivery"

  name_prefix         = var.name_prefix
  region              = var.region
  account_id          = local.account_id
  github_repository   = var.github_repository
  github_branch       = var.github_branch
  artifact_bucket     = module.storage.bucket_ids["artifacts"]
  artifact_bucket_arn = module.storage.bucket_arns["artifacts"]
  kms_key_arn         = var.kms_key_arn

  services       = local.services
  cluster_name   = module.ecs_platform.cluster_name
  api_endpoint   = module.apigw.api_endpoint
  desired_counts = var.desired_counts

  adot_repository_name = aws_ecr_repository.adot.name
  adot_source_image    = local.adot_source_image
  adot_image_tag       = local.adot_image_tag

  grafana_repository_name = aws_ecr_repository.grafana.name
  grafana_image_tag       = local.grafana_image_tag
  grafana_version         = local.grafana_version

  vpc_id            = module.network.vpc_id
  subnet_ids        = module.network.private_app_subnet_ids
  security_group_id = aws_security_group.db_bootstrap.id
  db_host           = module.rds.proxy_endpoint
  db_name           = module.rds.database_name
  master_secret_arn = module.rds.master_secret_arn

  depends_on = [
    module.service,
    aws_secretsmanager_secret_policy.db,
    aws_secretsmanager_secret_policy.daraja,
  ]
}

# ---------------------------------------------------------------------------
# Secret access policies
#
# Attached here rather than inside the secrets module — see the note on that
# module call. Defence in depth: a secret is readable only if BOTH the task
# role policy (ecs-service module) and this resource policy allow it.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "daraja_readers" {
  statement {
    sid    = "OnlyPaymentsMayReadDaraja"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = [module.service["payments"].task_role_arn]
    }

    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = ["*"]
  }
}

resource "aws_secretsmanager_secret_policy" "daraja" {
  secret_arn = module.secrets.secret_arns["daraja"]
  policy     = data.aws_iam_policy_document.daraja_readers.json
}

data "aws_iam_policy_document" "db_readers" {
  statement {
    sid    = "ServiceTaskRoles"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = [for s in local.services : module.service[s].task_role_arn]
    }

    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = ["*"]
  }
}

resource "aws_secretsmanager_secret_policy" "db" {
  secret_arn = module.secrets.secret_arns["db"]
  policy     = data.aws_iam_policy_document.db_readers.json
}

data "aws_iam_policy_document" "grafana_admin_readers" {
  statement {
    sid    = "GrafanaTaskRoleOnly"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = [module.grafana.task_role_arn]
    }

    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = ["*"]
  }
}

resource "aws_secretsmanager_secret_policy" "grafana_admin" {
  secret_arn = module.secrets.secret_arns["grafana-admin"]
  policy     = data.aws_iam_policy_document.grafana_admin_readers.json
}

data "aws_iam_policy_document" "slack_readers" {
  statement {
    sid    = "GrafanaAlerting"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = [module.grafana.task_role_arn]
    }

    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = ["*"]
  }
}

resource "aws_secretsmanager_secret_policy" "slack_webhook" {
  secret_arn = module.secrets.secret_arns["slack-webhook"]
  policy     = data.aws_iam_policy_document.slack_readers.json
}
