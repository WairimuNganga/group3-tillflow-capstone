# TillFlow dev environment.
#
#   internet → API Gateway → VPC Link → internal ALB → ECS Fargate (private)
#                                                        ├─ web
#                                                        ├─ pos
#                                                        ├─ payments   ← only service with internet egress
#                                                        └─ commission
#                                                             ↓
#                                    RDS Proxy → PostgreSQL · Valkey · SQS+DLQ
#
# Every task runs two containers: the application plus an ADOT sidecar.

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  services = ["web", "pos", "payments", "commission"]

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
  amp_remote_write_url = var.amp_remote_write_url

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
      DARAJA_CREDENTIALS = module.secrets.secret_arns["daraja"]
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

  client_security_group_ids = { for s in local.services : s => module.service[s].security_group_id }

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

module "messaging" {
  source = "../../modules/messaging"

  name_prefix = var.name_prefix
  account_id  = local.account_id
  kms_key_arn = var.kms_key_arn
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
