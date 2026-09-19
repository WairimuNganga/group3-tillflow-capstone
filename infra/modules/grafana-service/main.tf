# Self-hosted Grafana on ECS Fargate (ADR-001 Option B). Single container — no ADOT sidecar.
# AMP is queried over HTTPS with SigV4 using the task role.

locals {
  container_name = "grafana"
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/${var.name_prefix}/grafana"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn

  tags = {
    Name    = "${var.name_prefix}-grafana"
    service = "grafana"
  }
}

data "aws_prefix_list" "s3" {
  name = "com.amazonaws.${var.region}.s3"
}

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
  name               = "${var.name_prefix}-grafana-task"
  description        = "Grafana task role - AMP query and optional alert secrets"
  assume_role_policy = data.aws_iam_policy_document.task_assume.json

  tags = {
    Name    = "${var.name_prefix}-grafana-task"
    service = "grafana"
  }
}

data "aws_iam_policy_document" "task" {
  statement {
    sid = "QueryAmp"
    actions = [
      "aps:QueryMetrics",
      "aps:GetSeries",
      "aps:GetLabels",
      "aps:GetMetricMetadata",
    ]
    resources = [var.amp_workspace_arn]
  }

  dynamic "statement" {
    for_each = length(var.readable_secret_arns) > 0 ? [1] : []
    content {
      sid       = "ReadAlertSecrets"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = var.readable_secret_arns
    }
  }

  dynamic "statement" {
    for_each = length(var.readable_secret_arns) > 0 ? [1] : []
    content {
      sid       = "DecryptSecrets"
      actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
      resources = [var.kms_key_arn]
    }
  }

  statement {
    sid       = "ExecCommand"
    actions   = ["ssmmessages:CreateControlChannel", "ssmmessages:CreateDataChannel", "ssmmessages:OpenControlChannel", "ssmmessages:OpenDataChannel"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "grafana-permissions"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-grafana"
  description = "Grafana ECS task"
  vpc_id      = var.vpc_id

  tags = {
    Name    = "${var.name_prefix}-grafana"
    service = "grafana"
  }
}

resource "aws_vpc_security_group_ingress_rule" "from_alb" {
  security_group_id            = aws_security_group.this.id
  description                  = "HTTP from the ALB on port 3000"
  referenced_security_group_id = var.alb_security_group_id
  from_port                    = 3000
  to_port                      = 3000
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "internet_https" {
  security_group_id = aws_security_group.this.id
  description       = "HTTPS for AMP Prometheus query API (SigV4)"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "in_vpc" {
  security_group_id = aws_security_group.this.id
  description       = "In-VPC egress (VPC endpoints, DNS)"
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "-1"
}

resource "aws_vpc_security_group_egress_rule" "s3_gateway_https" {
  security_group_id = aws_security_group.this.id
  description       = "HTTPS to S3 gateway endpoint for ECR image layers"
  prefix_list_id    = data.aws_prefix_list.s3.id
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_ecs_task_definition" "this" {
  family                   = "${var.name_prefix}-grafana"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([{
    name      = local.container_name
    image     = var.image
    essential = true

    portMappings = [{
      containerPort = 3000
      protocol      = "tcp"
    }]

    environment = [
      { name = "AWS_REGION", value = var.region },
      { name = "AMP_PROMETHEUS_ENDPOINT", value = var.amp_prometheus_endpoint },
      { name = "GF_AUTH_ANONYMOUS_ENABLED", value = "false" },
      { name = "GF_SECURITY_ADMIN_USER", value = "admin" },
      { name = "GF_SERVER_SERVE_FROM_SUB_PATH", value = "true" },
      { name = "GF_SERVER_ROOT_URL", value = var.grafana_root_url },
      { name = "GF_SERVER_ENFORCE_DOMAIN", value = "false" },
      { name = "GF_USERS_ALLOW_SIGN_UP", value = "false" },
      { name = "GF_LOG_MODE", value = "console" },
    ]

    secrets = [{
      name      = "GF_SECURITY_ADMIN_PASSWORD"
      valueFrom = var.admin_password_secret_arn
    }]

    healthCheck = {
      command     = ["CMD-SHELL", "wget -q -O /dev/null http://127.0.0.1:3000/api/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.this.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "grafana"
      }
    }
  }])

  tags = {
    Name    = "${var.name_prefix}-grafana"
    service = "grafana"
  }
}

resource "aws_ecs_service" "this" {
  name            = "${var.name_prefix}-grafana"
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  enable_execute_command = var.enable_execute_command

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.this.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = local.container_name
    container_port   = 3000
  }

  health_check_grace_period_seconds = 120

  tags = {
    Name    = "${var.name_prefix}-grafana"
    service = "grafana"
  }

  lifecycle {
    ignore_changes = [desired_count]
  }
}
