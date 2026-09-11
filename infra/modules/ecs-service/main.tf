# One ECS Fargate service = TWO containers, always:
#   1. the application
#   2. an ADOT Collector sidecar
#
# The brief requires both. The app exports OTLP to localhost:4317 and never
# talks to AMP/X-Ray directly (ADR-008), so the sidecar is a hard dependency
# at startup, not an optional add-on — hence `dependsOn` below.

locals {
  # Image is addressed by DIGEST when one is supplied, by SHA tag otherwise.
  # `latest` is never valid here (ADR-009) — the validation on var.image_tag
  # rejects it outright rather than trusting convention.
  image = var.image_digest != null ? "${var.image_repository_url}@${var.image_digest}" : "${var.image_repository_url}:${var.image_tag}"

  app_container = {
    name      = var.service_name
    image     = local.image
    essential = true

    portMappings = [{
      name          = "${var.service_name}-http"
      containerPort = var.container_port
      protocol      = "tcp"
      appProtocol   = "http"
    }]

    # Non-root, read-only root filesystem (threat model T2.3). Writable paths
    # are explicit tmpfs mounts, so a compromised container cannot persist
    # anything to disk.
    user                   = var.container_user
    readonlyRootFilesystem = true

    mountPoints = [{
      sourceVolume  = "tmp"
      containerPath = "/tmp"
      readOnly      = false
    }]

    linuxParameters = {
      initProcessEnabled = true # reap zombies; also required for ECS Exec
    }

    environment = concat([
      { name = "SERVICE_NAME", value = var.service_name },
      { name = "ENVIRONMENT", value = var.environment },
      { name = "AWS_REGION", value = var.region },
      # Surfaced at /health so the post-deploy smoke check can assert that
      # what is running is what the pipeline built (ADR-009, T7.3).
      { name = "GIT_SHA", value = var.image_tag },
      { name = "IMAGE_DIGEST", value = coalesce(var.image_digest, "unset") },
      # OTLP to the sidecar on localhost — never straight to AMP (ADR-008).
      { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = "http://localhost:4317" },
      { name = "OTEL_SERVICE_NAME", value = var.service_name },
      { name = "OTEL_RESOURCE_ATTRIBUTES", value = "service.name=${var.service_name},deployment.environment=${var.environment}" },
      ], [
      for k, v in var.environment_variables : { name = k, value = v }
    ])

    # ARNs only. A value never appears in the task definition, in state, or in
    # a plan output (threat model T6.3).
    secrets = [for k, v in var.secrets : { name = k, valueFrom = v }]

    dependsOn = [{
      containerName = "adot"
      condition     = "START"
    }]

    healthCheck = {
      command     = ["CMD-SHELL", "curl -fsS http://localhost:${var.container_port}${var.health_path} || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = var.log_group_name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "app"
      }
    }
  }

  adot_container = {
    name = "adot"
    # Pinned by digest-able tag rather than :latest — the sidecar is in the
    # money path's telemetry chain and must not change under us silently.
    image = var.adot_image

    # NOT essential: a collector crash must not take the application down and
    # turn an observability outage into a customer-facing one.
    essential = false

    user                   = "0"
    readonlyRootFilesystem = false

    command = ["--config=/etc/ecs/${var.adot_config_file}"]

    environment = [
      { name = "AWS_PROMETHEUS_ENDPOINT", value = var.amp_remote_write_url },
      { name = "AWS_REGION", value = var.region },
    ]

    portMappings = [
      { containerPort = 4317, protocol = "tcp" }, # OTLP gRPC
      { containerPort = 4318, protocol = "tcp" }, # OTLP HTTP
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = var.log_group_name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "adot"
      }
    }
  }
}

# ---------------------------------------------------------------------------
# Task role — per service, and this is where least privilege actually bites
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "task_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
  }
}

resource "aws_iam_role" "task" {
  name               = "${var.name_prefix}-${var.service_name}-task"
  description        = "Task role for ${var.service_name}"
  assume_role_policy = data.aws_iam_policy_document.task_assume.json

  tags = {
    Name    = "${var.name_prefix}-${var.service_name}-task"
    service = var.service_name
  }
}

data "aws_iam_policy_document" "task" {
  # Telemetry: every task's sidecar writes metrics and traces.
  statement {
    sid = "Telemetry"
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
      "xray:GetSamplingRules",
      "xray:GetSamplingTargets",
      "aps:RemoteWrite",
      "cloudwatch:PutMetricData",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "ExecCommand"
    actions   = ["ssmmessages:CreateControlChannel", "ssmmessages:CreateDataChannel", "ssmmessages:OpenControlChannel", "ssmmessages:OpenDataChannel"]
    resources = ["*"]
  }

  # Only granted where the service actually needs it. `commission` gets no
  # Daraja secret and no B2C permission — it is technically unable to call
  # Daraja even if someone writes the code (threat model T3.1).
  dynamic "statement" {
    for_each = length(var.readable_secret_arns) > 0 ? [1] : []
    content {
      sid       = "ReadOwnSecrets"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = var.readable_secret_arns
    }
  }

  dynamic "statement" {
    for_each = length(var.sqs_send_arns) > 0 ? [1] : []
    content {
      sid       = "SqsSend"
      actions   = ["sqs:SendMessage", "sqs:GetQueueUrl", "sqs:GetQueueAttributes"]
      resources = var.sqs_send_arns
    }
  }

  dynamic "statement" {
    for_each = length(var.sqs_consume_arns) > 0 ? [1] : []
    content {
      sid       = "SqsConsume"
      actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes", "sqs:GetQueueUrl"]
      resources = var.sqs_consume_arns
    }
  }

  dynamic "statement" {
    for_each = length(var.readable_secret_arns) > 0 || length(var.sqs_send_arns) > 0 || length(var.sqs_consume_arns) > 0 ? [1] : []
    content {
      sid       = "DecryptWithSharedKey"
      actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
      resources = [var.kms_key_arn]
    }
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "service-permissions"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

# ---------------------------------------------------------------------------
# Security group
#
# Ingress from the ALB only for internet-facing services; egress is the
# interesting half — see var.allow_internet_egress.
# ---------------------------------------------------------------------------

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-${var.service_name}"
  description = "${var.service_name} task"
  vpc_id      = var.vpc_id

  tags = {
    Name    = "${var.name_prefix}-${var.service_name}"
    service = var.service_name
  }
}

# count keys off an explicit boolean, not off the SG id: the id is unknown
# until apply, and `count` must be resolvable at plan time.
resource "aws_vpc_security_group_ingress_rule" "from_alb" {
  count = var.attach_to_alb ? 1 : 0

  security_group_id = aws_security_group.this.id
  # No apostrophe: EC2 rejects it. Allowed set is a-zA-Z0-9 and . _ - : / ( ) # , @ [ ] + = & ; { } ! $ *
  description                  = "HTTP from the ALB on this service port only"
  referenced_security_group_id = var.alb_security_group_id
  from_port                    = var.container_port
  to_port                      = var.container_port
  ip_protocol                  = "tcp"
}

# Service Connect: named callers reach this service directly, bypassing the
# ALB entirely (T2.1/T3.2).
resource "aws_vpc_security_group_ingress_rule" "from_peers" {
  for_each = var.peer_security_group_ids

  security_group_id            = aws_security_group.this.id
  description                  = "Service Connect from ${each.key}"
  referenced_security_group_id = each.value
  from_port                    = var.container_port
  to_port                      = var.container_port
  ip_protocol                  = "tcp"
}

# Threat model T2.4 / AR-7. Only the service that actually talks to Daraja gets
# a route off the VPC. Everything else reaches AWS services through VPC
# endpoints and has no internet egress at all.
#
# This rule is 443-to-anywhere, not "Daraja only": security groups filter by
# CIDR/prefix list, not hostname, and Daraja publishes no stable range. The
# residual is accepted as AR-7 and watched via flow logs — it is deliberately
# NOT described as a Daraja allow-list.
resource "aws_vpc_security_group_egress_rule" "internet_https" {
  count = var.allow_internet_egress ? 1 : 0

  security_group_id = aws_security_group.this.id
  description       = "HTTPS to any host (AR-7 - hostname filtering is not expressible with SGs)"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

# Reaching VPC endpoints, RDS Proxy and the cache still needs egress, even for
# services with no internet route.
resource "aws_vpc_security_group_egress_rule" "in_vpc" {
  security_group_id = aws_security_group.this.id
  description       = "In-VPC egress (VPC endpoints, RDS Proxy, cache, Service Connect peers)"
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "-1"
}

# ---------------------------------------------------------------------------
# Task definition + service
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "this" {
  family                   = "${var.name_prefix}-${var.service_name}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  volume {
    name = "tmp"
  }

  container_definitions = jsonencode([local.app_container, local.adot_container])

  tags = {
    Name    = "${var.name_prefix}-${var.service_name}"
    service = var.service_name
  }
}

resource "aws_ecs_service" "this" {
  name            = "${var.name_prefix}-${var.service_name}"
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  enable_execute_command = var.enable_execute_command

  # Circuit breaker: a deploy that never reaches steady state rolls itself back
  # instead of sitting half-broken (ADR-009).
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.this.id]
    assign_public_ip = false # never (threat model T2.2)
  }

  dynamic "load_balancer" {
    for_each = var.attach_to_alb ? [var.target_group_arn] : []
    content {
      target_group_arn = load_balancer.value
      container_name   = var.service_name
      container_port   = var.container_port
    }
  }

  service_connect_configuration {
    enabled   = true
    namespace = var.service_connect_namespace_arn

    service {
      port_name      = "${var.service_name}-http"
      discovery_name = var.service_name

      client_alias {
        port     = var.container_port
        dns_name = var.service_name
      }
    }

    log_configuration {
      log_driver = "awslogs"
      options = {
        "awslogs-group"         = var.log_group_name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "service-connect"
      }
    }
  }

  # Give a new task time to boot both containers before the ALB starts
  # counting health-check failures against it.
  health_check_grace_period_seconds = var.attach_to_alb ? 60 : null

  tags = {
    Name    = "${var.name_prefix}-${var.service_name}"
    service = var.service_name
  }
}
