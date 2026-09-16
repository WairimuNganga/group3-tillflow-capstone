# G2 database bootstrap runner.
#
# Terraform creates the runner and its least-privilege permissions. The runner
# executes inside the VPC so it can reach the private RDS Proxy, creates the
# service schemas/roles, and writes service credentials to devops-g3/db. Secret
# values are generated during the build and do not pass through Terraform state.

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name_prefix}-db-bootstrap"
  description        = "CodeBuild role for G2 PostgreSQL schema and runtime role bootstrap"
  assume_role_policy = data.aws_iam_policy_document.assume.json

  tags = {
    Name    = "${var.name_prefix}-db-bootstrap"
    service = "platform"
  }
}

data "aws_iam_policy_document" "this" {
  statement {
    sid = "Logs"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:${var.region}:${var.account_id}:log-group:/${var.name_prefix}/codebuild/db-bootstrap*"]
  }

  statement {
    sid = "ReadMasterSecret"
    actions = [
      "secretsmanager:DescribeSecret",
      "secretsmanager:GetSecretValue",
    ]
    resources = [var.master_secret_arn]
  }

  statement {
    sid = "WriteServiceDbSecret"
    actions = [
      "secretsmanager:DescribeSecret",
      # Read is required, not optional: the buildspec reuses any password
      # already stored so a re-run is a no-op. Without it the read fails
      # silently (`2>/dev/null || true`), EXISTING_DB_JSON stays empty, and
      # every run regenerates all four passwords — ALTER ROLE mid-flight,
      # breaking new connections from tasks still holding the old credential.
      # The idempotency would be written but inert.
      "secretsmanager:GetSecretValue",
      "secretsmanager:PutSecretValue",
      "secretsmanager:UpdateSecret",
    ]
    resources = [var.db_secret_arn]
  }

  statement {
    sid       = "GeneratePasswords"
    actions   = ["secretsmanager:GetRandomPassword"]
    resources = ["*"]
  }

  statement {
    sid = "KmsForSecrets"
    actions = [
      "kms:Decrypt",
      "kms:Encrypt",
      "kms:GenerateDataKey",
      "kms:DescribeKey",
    ]
    resources = [var.kms_key_arn]
  }

  # Required for CodeBuild projects that attach to a VPC.
  statement {
    sid = "VpcNetworkInterfaces"
    actions = [
      "ec2:CreateNetworkInterface",
      "ec2:CreateNetworkInterfacePermission",
      "ec2:DeleteNetworkInterface",
      "ec2:DescribeDhcpOptions",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeSubnets",
      "ec2:DescribeVpcs",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "Identity"
    actions   = ["sts:GetCallerIdentity"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "this" {
  name   = "db-bootstrap"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.this.json
}

resource "aws_codebuild_project" "this" {
  name          = "${var.name_prefix}-db-bootstrap"
  description   = "Create G2 PostgreSQL schemas, runtime roles and service DB credentials"
  service_role  = aws_iam_role.this.arn
  build_timeout = 20

  # CODEPIPELINE rather than NO_SOURCE/NO_ARTIFACTS so this can run as a
  # pipeline stage before DeployEcs — ECS cannot start a task until
  # devops-g3/db holds a value, so the ordering has to be enforced, not
  # remembered. Consequence: `aws codebuild start-build` no longer works on
  # this project; re-run it by retrying the DbBootstrap stage (see runbook).
  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = var.codebuild_image
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"

    environment_variable {
      name  = "NAME_PREFIX"
      value = var.name_prefix
    }

    environment_variable {
      name  = "SERVICES"
      value = join(" ", var.services)
    }

    environment_variable {
      name  = "DB_HOST"
      value = var.db_host
    }

    environment_variable {
      name  = "DB_NAME"
      value = var.db_name
    }

    environment_variable {
      name  = "MASTER_SECRET_ARN"
      value = var.master_secret_arn
    }

    environment_variable {
      name  = "DB_SECRET_ARN"
      value = var.db_secret_arn
    }
  }

  # Path within the source artifact, not an inlined file(). The SQL is now
  # versioned with the commit that deploys it, the same as the other two
  # buildspecs, instead of only changing on a Terraform apply.
  source {
    type      = "CODEPIPELINE"
    buildspec = "infra/modules/db-bootstrap/buildspec.yml"
  }

  vpc_config {
    vpc_id             = var.vpc_id
    subnets            = var.subnet_ids
    security_group_ids = [var.security_group_id]
  }

  logs_config {
    cloudwatch_logs {
      group_name  = "/${var.name_prefix}/codebuild/db-bootstrap"
      stream_name = "db"
    }
  }

  tags = {
    Name    = "${var.name_prefix}-db-bootstrap"
    service = "platform"
  }
}
