# AWS-native delivery lane from the trainer guide:
#
#   GitHub CodeConnection -> CodePipeline -> CodeBuild -> ECR/SSM -> ECS -> smoke
#
# Terraform owns the pipeline and build projects. The GitHub connection still
# needs the normal one-time AWS console authorization after creation.

locals {
  image_artifact_names = { for svc in var.services : svc => "${replace(svc, "-", "_")}_image" }
}

resource "aws_ssm_parameter" "image_tag" {
  for_each = toset(var.services)

  name  = "/${var.name_prefix}/${each.key}/image-tag"
  type  = "String"
  value = "REPLACE_ME"

  tags = {
    Name    = "${var.name_prefix}-${each.key}-image-tag"
    service = each.key
  }

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "image_digest" {
  for_each = toset(var.services)

  name  = "/${var.name_prefix}/${each.key}/image-digest"
  type  = "String"
  value = "UNSET"

  tags = {
    Name    = "${var.name_prefix}-${each.key}-image-digest"
    service = each.key
  }

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_codestarconnections_connection" "github" {
  name          = "${var.name_prefix}-github"
  provider_type = "GitHub"

  tags = {
    Name    = "${var.name_prefix}-github"
    service = "delivery"
  }
}

data "aws_iam_policy_document" "codebuild_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "codebuild" {
  name               = "${var.name_prefix}-codebuild"
  description        = "CodeBuild role for TillFlow service image builds and smoke checks"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume.json

  tags = {
    Name    = "${var.name_prefix}-codebuild"
    service = "delivery"
  }
}

data "aws_iam_policy_document" "codebuild" {
  statement {
    sid = "ArtifactBucket"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:PutObject",
      "s3:ListBucket",
    ]
    resources = [var.artifact_bucket_arn, "${var.artifact_bucket_arn}/*"]
  }

  statement {
    sid = "Logs"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:${var.region}:${var.account_id}:log-group:/${var.name_prefix}/codebuild*"]
  }

  statement {
    sid = "EcrBuildPushAndScan"
    actions = [
      "ecr:GetAuthorizationToken",
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:DescribeImages",
      "ecr:StartImageScan",
      "ecr:DescribeImageScanFindings",
    ]
    resources = ["*"]
  }

  statement {
    sid = "RecordImageVersions"
    actions = [
      "ssm:PutParameter",
      "ssm:AddTagsToResource",
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:ListTagsForResource",
    ]
    resources = [
      "arn:aws:ssm:${var.region}:${var.account_id}:parameter/${var.name_prefix}/*/image-tag",
      "arn:aws:ssm:${var.region}:${var.account_id}:parameter/${var.name_prefix}/*/image-digest",
    ]
  }

  statement {
    sid = "ReadRdsMasterSecretForMigrations"
    actions = [
      "secretsmanager:DescribeSecret",
      "secretsmanager:GetSecretValue",
    ]
    resources = [var.master_secret_arn]
  }

  statement {
    sid = "EcsSmokeAndScale"
    actions = [
      "ecs:DescribeServices",
      "ecs:UpdateService",
      "ecs:ListTasks",
      "ecs:DescribeTasks",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "KmsForArtifactsAndEcr"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
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

resource "aws_iam_role_policy" "codebuild" {
  name   = "delivery-build"
  role   = aws_iam_role.codebuild.id
  policy = data.aws_iam_policy_document.codebuild.json
}

resource "aws_codebuild_project" "image" {
  for_each = toset(var.services)

  name          = "${var.name_prefix}-${each.key}-build"
  description   = "Build, scan and push the ${each.key} image"
  service_role  = aws_iam_role.codebuild.arn
  build_timeout = 30

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = var.codebuild_image
    type                        = "ARM_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = true

    environment_variable {
      name  = "SERVICE_NAME"
      value = each.key
    }

    # Must match mirror-adot + Terraform task def (buildspec default was tillflow1).
    environment_variable {
      name  = "ADOT_IMAGE_TAG"
      value = var.adot_image_tag
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = "buildspecs/service-image.yml"
  }

  logs_config {
    cloudwatch_logs {
      group_name  = "/${var.name_prefix}/codebuild/${each.key}"
      stream_name = "image"
    }
  }

  tags = {
    Name    = "${var.name_prefix}-${each.key}-build"
    service = each.key
  }
}

resource "aws_codebuild_project" "adot_mirror" {
  name          = "${var.name_prefix}-adot-mirror"
  description   = "Build private ADOT image (upstream pin + TillFlow AMP config)"
  service_role  = aws_iam_role.codebuild.arn
  build_timeout = 15

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = var.codebuild_image
    type                        = "ARM_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = true

    environment_variable {
      name  = "ADOT_REPOSITORY"
      value = var.adot_repository_name
    }

    environment_variable {
      name  = "ADOT_SOURCE_IMAGE"
      value = var.adot_source_image
    }

    environment_variable {
      name  = "ADOT_IMAGE_TAG"
      value = var.adot_image_tag
    }

    environment_variable {
      name  = "IMAGE_PLATFORM"
      value = "linux/arm64"
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = "buildspecs/mirror-adot.yml"
  }

  logs_config {
    cloudwatch_logs {
      group_name  = "/${var.name_prefix}/codebuild/adot-mirror"
      stream_name = "image"
    }
  }

  tags = {
    Name    = "${var.name_prefix}-adot-mirror"
    service = "telemetry"
  }
}

resource "aws_codebuild_project" "smoke" {
  name          = "${var.name_prefix}-smoke"
  description   = "Scale ECS services after image deploy and run smoke checks"
  service_role  = aws_iam_role.codebuild.arn
  build_timeout = 30

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/standard:7.0"
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"

    environment_variable {
      name  = "API_ENDPOINT"
      value = var.api_endpoint
    }

    dynamic "environment_variable" {
      for_each = var.desired_counts
      content {
        name  = "${upper(replace(environment_variable.key, "-", "_"))}_DESIRED_COUNT"
        value = tostring(environment_variable.value)
      }
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = "buildspecs/post-deploy-smoke.yml"
  }

  logs_config {
    cloudwatch_logs {
      group_name  = "/${var.name_prefix}/codebuild/smoke"
      stream_name = "smoke"
    }
  }

  tags = {
    Name    = "${var.name_prefix}-smoke"
    service = "delivery"
  }
}

resource "aws_codebuild_project" "pos_migrations" {
  name          = "${var.name_prefix}-pos-migrations"
  description   = "Run POS Alembic migrations against RDS before ECS deploy"
  service_role  = aws_iam_role.codebuild.arn
  build_timeout = 20

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = var.codebuild_image
    type                        = "ARM_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = true

    environment_variable {
      name  = "NAME_PREFIX"
      value = var.name_prefix
    }

    environment_variable {
      name  = "POS_REPOSITORY"
      value = "${var.name_prefix}/pos"
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
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = "buildspecs/pos-migrations.yml"
  }

  vpc_config {
    vpc_id             = var.vpc_id
    subnets            = var.subnet_ids
    security_group_ids = [var.security_group_id]
  }

  logs_config {
    cloudwatch_logs {
      group_name  = "/${var.name_prefix}/codebuild/pos-migrations"
      stream_name = "migrate"
    }
  }

  tags = {
    Name    = "${var.name_prefix}-pos-migrations"
    service = "pos"
  }
}

data "aws_iam_policy_document" "codepipeline_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codepipeline.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "codepipeline" {
  name               = "${var.name_prefix}-pipeline"
  description        = "CodePipeline role for TillFlow app delivery"
  assume_role_policy = data.aws_iam_policy_document.codepipeline_assume.json

  tags = {
    Name    = "${var.name_prefix}-pipeline"
    service = "delivery"
  }
}

data "aws_iam_policy_document" "codepipeline" {
  statement {
    sid = "ArtifactBucket"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:GetBucketVersioning",
      "s3:PutObject",
      "s3:ListBucket",
    ]
    resources = [var.artifact_bucket_arn, "${var.artifact_bucket_arn}/*"]
  }

  statement {
    sid       = "UseGithubConnection"
    actions   = ["codestar-connections:UseConnection", "codeconnections:UseConnection"]
    resources = [aws_codestarconnections_connection.github.arn]
  }

  statement {
    sid     = "RunBuilds"
    actions = ["codebuild:StartBuild", "codebuild:BatchGetBuilds"]
    resources = concat(
      [for p in aws_codebuild_project.image : p.arn],
      [
        aws_codebuild_project.adot_mirror.arn,
        aws_codebuild_project.pos_migrations.arn,
        aws_codebuild_project.smoke.arn,
      ],
    )
  }

  # Permissions required by the ECS standard deploy action. RegisterTaskDefinition
  # requires wildcard resource scope, and ecs:TagResource is required when ECS
  # tagging authorization is enforced for task-definition registration.
  statement {
    sid = "DeployToEcs"
    actions = [
      "ecs:DescribeClusters",
      "ecs:DescribeServices",
      "ecs:DescribeTaskDefinition",
      "ecs:DescribeTasks",
      "ecs:ListTasks",
      "ecs:RegisterTaskDefinition",
      "ecs:TagResource",
      "ecs:UpdateService",
    ]
    resources = ["*"]
  }

  # Registering a task definition requires passing the execution and task roles.
  # The role scope is limited to this project's prefix and the ECS service
  # principals used by the standard deploy action.
  statement {
    sid       = "PassTaskRoles"
    actions   = ["iam:PassRole"]
    resources = ["arn:aws:iam::${var.account_id}:role/${var.name_prefix}-*"]

    condition {
      test     = "StringEqualsIfExists"
      variable = "iam:PassedToService"
      values   = ["ecs.amazonaws.com", "ecs-tasks.amazonaws.com"]
    }
  }

  statement {
    sid       = "KmsForArtifacts"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "codepipeline" {
  name   = "delivery-pipeline"
  role   = aws_iam_role.codepipeline.id
  policy = data.aws_iam_policy_document.codepipeline.json
}

resource "aws_codepipeline" "this" {
  name     = "${var.name_prefix}-pipeline"
  role_arn = aws_iam_role.codepipeline.arn

  artifact_store {
    location = var.artifact_bucket
    type     = "S3"

    encryption_key {
      id   = var.kms_key_arn
      type = "KMS"
    }
  }

  stage {
    name = "Source"

    action {
      name             = "GitHub"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      output_artifacts = ["source_output"]

      configuration = {
        ConnectionArn    = aws_codestarconnections_connection.github.arn
        FullRepositoryId = var.github_repository
        BranchName       = var.github_branch
        DetectChanges    = "true"
      }
    }
  }

  stage {
    name = "BuildScanPush"

    action {
      name            = "mirror-adot"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      input_artifacts = ["source_output"]
      version         = "1"
      run_order       = 1

      configuration = {
        ProjectName = aws_codebuild_project.adot_mirror.name
      }
    }

    dynamic "action" {
      for_each = toset(var.services)
      content {
        name             = "build-${action.key}"
        category         = "Build"
        owner            = "AWS"
        provider         = "CodeBuild"
        input_artifacts  = ["source_output"]
        output_artifacts = [local.image_artifact_names[action.key]]
        version          = "1"
        run_order        = 2

        configuration = {
          ProjectName = aws_codebuild_project.image[action.key].name
        }
      }
    }
  }

  stage {
    name = "MigrateDb"

    action {
      name            = "pos-alembic"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      input_artifacts = ["source_output"]
      version         = "1"
      run_order       = 1

      configuration = {
        ProjectName = aws_codebuild_project.pos_migrations.name
      }
    }
  }

  stage {
    name = "DeployEcs"

    dynamic "action" {
      for_each = toset(var.services)
      content {
        name            = "deploy-${action.key}"
        category        = "Deploy"
        owner           = "AWS"
        provider        = "ECS"
        input_artifacts = [local.image_artifact_names[action.key]]
        version         = "1"
        run_order       = 1

        configuration = {
          ClusterName = var.cluster_name
          ServiceName = "${var.name_prefix}-${action.key}"
          FileName    = "imagedefinitions.json"
        }
      }
    }
  }

  stage {
    name = "Smoke"

    action {
      name            = "scale-and-smoke"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      input_artifacts = ["source_output"]
      version         = "1"
      run_order       = 1

      configuration = {
        ProjectName = aws_codebuild_project.smoke.name
      }
    }
  }

  tags = {
    Name    = "${var.name_prefix}-pipeline"
    service = "delivery"
  }
}
