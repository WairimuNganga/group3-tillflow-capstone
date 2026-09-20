locals {
  base_url    = trimsuffix(var.api_base_url, "/")
  health_url  = "${local.base_url}/health"
  ready_url   = "${local.base_url}/ready"
  canary_name = "${var.name_prefix}-edge-health"
  s3_prefix   = "canary/"
}

resource "aws_s3_bucket" "artifacts" {
  bucket = "${var.name_prefix}-synthetics-${var.account_id}"

  tags = {
    Name    = "${var.name_prefix}-synthetics"
    service = "platform"
    owner   = var.owner_tag
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

data "archive_file" "canary_zip" {
  type        = "zip"
  source_file = "${path.module}/canary.js"
  output_path = "${path.module}/.canary.zip"
}

data "aws_iam_policy_document" "canary_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "canary" {
  name               = "${var.name_prefix}-synthetics-canary"
  assume_role_policy = data.aws_iam_policy_document.canary_assume.json

  tags = {
    Name    = "${var.name_prefix}-synthetics-canary"
    service = "platform"
    owner   = var.owner_tag
  }
}

data "aws_iam_policy_document" "canary" {
  statement {
    sid    = "CanaryArtifacts"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetBucketLocation",
    ]
    resources = [
      aws_s3_bucket.artifacts.arn,
      "${aws_s3_bucket.artifacts.arn}/${local.s3_prefix}*",
    ]
  }

  statement {
    sid    = "CanaryLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:${var.region}:${var.account_id}:log-group:/aws/lambda/cwsyn-*"]
  }

  statement {
    sid    = "CanaryMetrics"
    effect = "Allow"
    actions = [
      "cloudwatch:PutMetricData",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["CloudWatchSynthetics"]
    }
  }
}

resource "aws_iam_role_policy" "canary" {
  name   = "synthetics-canary"
  role   = aws_iam_role.canary.id
  policy = data.aws_iam_policy_document.canary.json
}

resource "aws_s3_bucket_policy" "canary_artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudWatchSyntheticsArtifacts"
        Effect    = "Allow"
        Principal = { Service = "synthetics.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.artifacts.arn}/${local.s3_prefix}*"
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = var.account_id
          }
        }
      },
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.artifacts]
}

resource "aws_synthetics_canary" "edge_health" {
  name                 = local.canary_name
  artifact_s3_location = "s3://${aws_s3_bucket.artifacts.id}/${local.s3_prefix}"
  execution_role_arn   = aws_iam_role.canary.arn
  handler              = "canary.handler"
  runtime_version      = var.runtime_version
  start_canary         = true
  zip_file             = data.archive_file.canary_zip.output_path

  schedule {
    expression = var.schedule_expression
  }

  run_config {
    timeout_in_seconds = 60
    environment_variables = {
      HEALTH_URL = local.health_url
      READY_URL  = local.ready_url
    }
  }

  tags = {
    Name    = local.canary_name
    service = "platform"
    owner   = var.owner_tag
  }

  depends_on = [
    aws_iam_role_policy.canary,
    aws_s3_bucket_policy.canary_artifacts,
  ]
}
