# Shared ECS foundation: cluster, ECR repositories, log groups, the execution
# role, and the Service Connect namespace that carries internal traffic.
#
# Service Connect (not the ALB) is how services talk to each other — threat
# model T2.1/T3.2: the ALB carries external traffic only, so there is no
# legitimate in-VPC caller of the ALB to carve an SG exception for.

resource "aws_ecs_cluster" "this" {
  name = var.name_prefix

  setting {
    name  = "containerInsights"
    value = "enhanced"
  }

  configuration {
    execute_command_configuration {
      kms_key_id = var.kms_key_arn
      logging    = "OVERRIDE"

      log_configuration {
        cloud_watch_encryption_enabled = true
        cloud_watch_log_group_name     = aws_cloudwatch_log_group.exec.name
      }
    }
  }

  tags = { Name = var.name_prefix }
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = aws_ecs_cluster.this.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

# ECS Exec session logs. Every exec into a running task is recorded — the
# closest thing to an audit trail for "someone shelled into payments".
resource "aws_cloudwatch_log_group" "exec" {
  name              = "/${var.name_prefix}/ecs-exec"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
}

# Internal service discovery. `payments.tillflow.local` resolves without ever
# touching the ALB.
resource "aws_service_discovery_http_namespace" "this" {
  name        = var.service_connect_namespace
  description = "Service Connect namespace for internal ${var.name_prefix} traffic"

  tags = { Name = "${var.name_prefix}-namespace" }
}

# ---------------------------------------------------------------------------
# ECR — one repository per service
#
# Naming uses the slash form from the brief: devops-g3/payments.
# ---------------------------------------------------------------------------

resource "aws_ecr_repository" "service" {
  for_each = toset(var.services)

  name                 = "${var.name_prefix}/${each.key}"
  image_tag_mutability = "IMMUTABLE" # a tag names exactly one build, forever (ADR-009)

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = var.kms_key_arn
  }

  tags = {
    Name    = "${var.name_prefix}-${each.key}"
    service = each.key
  }
}

resource "aws_ecr_lifecycle_policy" "service" {
  for_each = aws_ecr_repository.service

  repository = each.value.name

  # Count-based, NOT age-based. Rollback depends on old images still existing
  # (ADR-009 consequences) — an age-only rule could delete the exact image a
  # rollback needs.
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last ${var.ecr_image_retention_count} images so rollback targets survive"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = var.ecr_image_retention_count
      }
      action = { type = "expire" }
    }]
  })
}

# ---------------------------------------------------------------------------
# Log groups — one per service, named per the brief (/devops-g3/pos)
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "service" {
  for_each = toset(var.services)

  name              = "/${var.name_prefix}/${each.key}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn

  tags = {
    Name    = "${var.name_prefix}-${each.key}"
    service = each.key
  }
}

# ---------------------------------------------------------------------------
# Execution role
#
# One shared execution role: it only pulls images and writes logs, identical
# for every service. The TASK roles (what the application itself can do) are
# per-service and live in the ecs-service module — that is where least
# privilege actually matters.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "task_execution_assume" {
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

resource "aws_iam_role" "task_execution" {
  name               = "${var.name_prefix}-exec"
  description        = "Shared ECS task execution role — image pull + log write only"
  assume_role_policy = data.aws_iam_policy_document.task_execution_assume.json

  tags = { Name = "${var.name_prefix}-exec" }
}

resource "aws_iam_role_policy_attachment" "task_execution" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The execution role injects secrets into the container at start. It needs
# GetSecretValue on the secrets a task references, and Decrypt on the CMK.
data "aws_iam_policy_document" "task_execution_extra" {
  statement {
    sid       = "PullSecretsForInjection"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = length(var.secret_arns) > 0 ? var.secret_arns : ["arn:aws:secretsmanager:*:${var.account_id}:secret:${var.name_prefix}/*"]
  }

  statement {
    sid       = "DecryptSecretsAndLogs"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "task_execution_extra" {
  name   = "inject-secrets"
  role   = aws_iam_role.task_execution.id
  policy = data.aws_iam_policy_document.task_execution_extra.json
}
