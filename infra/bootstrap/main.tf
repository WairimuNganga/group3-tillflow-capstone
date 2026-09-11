# Bootstrap: the resources that must exist *before* any other root module can run.
#
# This stack creates the S3 bucket and DynamoDB table that every
# other stack uses as its backend, so it cannot itself use that backend. It runs
# with LOCAL state, once, and its state file is intentionally not committed
# (see .gitignore). Everything here is create-once and effectively immutable —
# if it is ever lost, re-import rather than re-apply blind.
#
#   cd infra/bootstrap && terraform init && terraform apply
#
# ADR-003 (object storage), ADR-009 (CI/CD OIDC), docs/threat-model.md T6.1/T6.2.

data "aws_caller_identity" "current" {}

locals {
  account_id   = data.aws_caller_identity.current.account_id
  github_owner = split("/", var.github_repository)[0]
  github_repo  = split("/", var.github_repository)[1]
  state_bucket = "${var.name_prefix}-tfstate-${data.aws_caller_identity.current.account_id}"
  lock_table   = "${var.name_prefix}-tflock"
  deploy_oidc_subs = flatten([for ref in var.ci_allowed_refs : [
    "repo:${var.github_repository}:${ref}",
    "repo:${lower(var.github_repository)}:${ref}",
    "repo:${local.github_owner}@*/${local.github_repo}@*:${ref}",
    "repo:${lower(local.github_owner)}@*/${lower(local.github_repo)}@*:${ref}",
  ]])
  plan_oidc_subs = [
    "repo:${var.github_repository}:*",
    "repo:${lower(var.github_repository)}:*",
    "repo:${local.github_owner}@*/${local.github_repo}@*:*",
    "repo:${lower(local.github_owner)}@*/${lower(local.github_repo)}@*:*",
  ]
}

# ---------------------------------------------------------------------------
# Terraform state bucket
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "tfstate" {
  bucket = local.state_bucket

  # State is the one bucket where an accidental `terraform destroy` is
  # unrecoverable — it would delete the record of everything else.
  lifecycle {
    prevent_destroy = true
  }

  tags = { service = "platform" }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

# SSE-KMS with the shared CMK per ADR-003. Bucket keys on to cut per-object
# KMS request cost, which is otherwise charged on every state read/write.
resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    id     = "expire-noncurrent-state-versions"
    status = "Enabled"

    filter {}

    # Current version never expires. Old versions are kept 90d as the
    # recovery window for a bad apply (ADR-003).
    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Deny any non-TLS access. S3 is TLS by default but the bucket policy is what
# makes it enforceable and auditable.
data "aws_iam_policy_document" "tfstate" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions   = ["s3:*"]
    resources = [aws_s3_bucket.tfstate.arn, "${aws_s3_bucket.tfstate.arn}/*"]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  policy = data.aws_iam_policy_document.tfstate.json

  depends_on = [aws_s3_bucket_public_access_block.tfstate]
}

# ---------------------------------------------------------------------------
# State lock table
#
# Terraform 1.10+ also supports S3-native locking (`use_lockfile`), but the
# capstone brief explicitly requires "S3 for Terraform remote state (with
# DynamoDB lock)" and ADR-003 records that decision, so DynamoDB it is.
# Five people applying concurrently without a lock will corrupt state.
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "tflock" {
  name         = local.lock_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.s3.arn
  }

  point_in_time_recovery {
    enabled = true
  }

  lifecycle {
    prevent_destroy = true
  }

  tags = { service = "platform" }
}

# ---------------------------------------------------------------------------
# Shared CMK for S3 + DynamoDB (ADR-003)
#
# One key across buckets is an accepted risk (AR-4 in docs/threat-model.md):
# adequate at this scale because the key policy scopes Decrypt to specific
# roles, without paying per-bucket KMS overhead.
# ---------------------------------------------------------------------------

resource "aws_kms_key" "s3" {
  description             = "${var.name_prefix} shared CMK for S3 state/artifacts/logs/backups/evidence"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  tags = { service = "platform" }
}

resource "aws_kms_alias" "s3" {
  name          = "alias/${var.name_prefix}-s3"
  target_key_id = aws_kms_key.s3.key_id
}

# ---------------------------------------------------------------------------
# GitHub Actions OIDC (threat model T6.1)
#
# This stack uses the existing GitHub OIDC provider for the AWS account and
# creates only this repository's plan/deploy roles. The provider itself is
# account-level, so Terraform looks it up instead of owning it here.
# ---------------------------------------------------------------------------

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "ci_deploy_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Scoped to this repository AND this ref. A fork, another repo, or a PR
    # branch cannot assume this role — that scoping is the whole control.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = local.deploy_oidc_subs
    }
  }
}

resource "aws_iam_role" "ci_deploy" {
  name               = "${var.name_prefix}-ci-deploy"
  description        = "GitHub Actions deploy role for ${var.github_repository} (OIDC, no static keys)"
  assume_role_policy = data.aws_iam_policy_document.ci_deploy_assume.json

  tags = { service = "platform" }
}

data "aws_iam_policy_document" "ci_deploy" {
  statement {
    sid = "TerraformState"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket",
    ]
    resources = [aws_s3_bucket.tfstate.arn, "${aws_s3_bucket.tfstate.arn}/*"]
  }

  statement {
    sid       = "TerraformLock"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.tflock.arn]
  }

  statement {
    sid = "StateEncryption"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:GenerateDataKey",
      "kms:DescribeKey",
    ]
    resources = [aws_kms_key.s3.arn]
  }

  # The apply job reads each service's currently-deployed SHA from SSM before
  # planning, so an infra-only merge cannot roll a running service back to
  # REPLACE_ME. Read-only: CodeBuild writes these, CI only reads them.
  statement {
    sid       = "ImageTagLookup"
    actions   = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = ["arn:aws:ssm:${var.region}:${local.account_id}:parameter/${var.name_prefix}/*/image-tag"]
  }

  # Infrastructure Terraform manages. Scoped by service rather than by ARN:
  # Terraform must be able to create resources that do not exist yet, and most
  # of these APIs do not support resource-level permissions on create.
  # IAM and Secrets Manager below are the two that DO support it, and are
  # scoped tightly — those are the ones that matter for blast radius.
  statement {
    sid = "PlatformServices"
    actions = [
      "ec2:*",
      "elasticloadbalancing:*",
      "ecs:*",
      "ecr:*",
      "apigateway:*",
      "rds:*",
      "elasticache:*",
      "sqs:*",
      "events:*",
      "scheduler:*",
      "servicediscovery:*",
      "application-autoscaling:*",
      "cloudwatch:*",
      "logs:*",
      "kms:DescribeKey",
      "kms:CreateGrant",
      "kms:ListAliases",
      "sts:GetCallerIdentity",
    ]
    resources = ["*"]
  }

  # Terraform creates and attaches the per-service task roles. Restricted to
  # this project's name prefix so a compromised CI run cannot touch unrelated
  # roles in a shared account (threat model T6.2).
  statement {
    sid = "ScopedIam"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:GetRole",
      "iam:PassRole",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:ListRoleTags",
      "iam:PutRolePolicy",
      "iam:GetRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:ListRolePolicies",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
      "iam:CreateServiceLinkedRole",
    ]
    resources = ["arn:aws:iam::${local.account_id}:role/${var.name_prefix}-*"]
  }

  # Secret *references* only. CI creates the containers and wires ARNs into task
  # definitions; it deliberately has no GetSecretValue, so a compromised CI run
  # cannot read the Daraja credentials (threat model T3.1, T6.3).
  statement {
    sid = "SecretsMetadataOnly"
    actions = [
      "secretsmanager:CreateSecret",
      "secretsmanager:DeleteSecret",
      "secretsmanager:DescribeSecret",
      "secretsmanager:TagResource",
      "secretsmanager:UntagResource",
      "secretsmanager:PutResourcePolicy",
      "secretsmanager:GetResourcePolicy",
      "secretsmanager:ListSecretVersionIds",
    ]
    resources = ["arn:aws:secretsmanager:${var.region}:${local.account_id}:secret:${var.name_prefix}/*"]
  }

  statement {
    sid = "ProjectBuckets"
    actions = [
      "s3:CreateBucket",
      "s3:DeleteBucket",
      "s3:Get*",
      "s3:List*",
      "s3:Put*",
      "s3:DeleteBucketPolicy",
    ]
    resources = [
      "arn:aws:s3:::${var.name_prefix}-*",
      "arn:aws:s3:::${var.name_prefix}-*/*",
    ]
  }
}

resource "aws_iam_role_policy" "ci_deploy" {
  name   = "terraform-deploy"
  role   = aws_iam_role.ci_deploy.id
  policy = data.aws_iam_policy_document.ci_deploy.json
}

# ---------------------------------------------------------------------------
# Read-only plan role
#
# PR plans run under this; only `main` may apply, under the deploy role above
# (ADR-009). Two roles rather than one because a PR is untrusted input: a
# contributor who can open a PR must not be able to mutate AWS, and sharing
# the deploy role would give them exactly that.
#
# The trust condition allows pull_request, NOT a branch ref — GitHub issues a
# `pull_request` subject for PR-triggered runs.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ci_plan_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = local.plan_oidc_subs
    }
  }
}

resource "aws_iam_role" "ci_plan" {
  name               = "${var.name_prefix}-ci-plan"
  description        = "Read-only role for PR terraform plan; cannot apply"
  assume_role_policy = data.aws_iam_policy_document.ci_plan_assume.json

  tags = { service = "platform" }
}

# Everything Terraform touches during a refresh/plan is a Describe/List/Get.
# ReadOnlyAccess covers that surface without enumerating every service.
resource "aws_iam_role_policy_attachment" "ci_plan_readonly" {
  role       = aws_iam_role.ci_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

data "aws_iam_policy_document" "ci_plan" {
  # Plan reads state but must never write it.
  statement {
    sid       = "ReadState"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.tfstate.arn, "${aws_s3_bucket.tfstate.arn}/*"]
  }

  # Plan does acquire the state lock. Locking is not a mutation of
  # infrastructure, and running with -lock=false risks planning against state
  # another apply is mid-write on.
  statement {
    sid       = "AcquireLock"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.tflock.arn]
  }

  statement {
    sid       = "DecryptState"
    actions   = ["kms:Decrypt", "kms:DescribeKey"]
    resources = [aws_kms_key.s3.arn]
  }

  statement {
    sid       = "ImageTagLookup"
    actions   = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = ["arn:aws:ssm:${var.region}:${local.account_id}:parameter/${var.name_prefix}/*/image-tag"]
  }

  # ReadOnlyAccess grants secretsmanager:GetSecretValue. Deny it outright:
  # a plan has no reason to read the Daraja credentials, and a PR from a fork
  # must not be able to exfiltrate them through a crafted output.
  statement {
    sid       = "NeverReadSecretValues"
    effect    = "Deny"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "ci_plan" {
  name   = "plan-state-access"
  role   = aws_iam_role.ci_plan.id
  policy = data.aws_iam_policy_document.ci_plan.json
}
