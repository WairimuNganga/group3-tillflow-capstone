# Project buckets per ADR-003 — one bucket per purpose, not one bucket with
# prefixes, so lifecycle/retention mistakes on one purpose cannot touch another.
#
# The tfstate bucket is NOT here: it lives in infra/bootstrap because it must
# exist before this stack can have a backend.

locals {
  legacy_elb_log_delivery_account_ids = {
    us-west-1 = "027434742980"
  }
  legacy_elb_log_delivery_account_id = lookup(local.legacy_elb_log_delivery_account_ids, var.region, null)

  # Encryption is per-bucket rather than uniform because ALB log delivery does
  # not support a customer-managed KMS key — see the alb-logs entry.
  buckets = {
    artifacts = {
      purpose       = "Pipeline and build artifacts"
      kms           = true
      transition_ia = 30
      expire_days   = 180
      force_destroy = true
    }
    logs = {
      purpose       = "Application and service logs"
      kms           = true
      transition_ia = 30
      expire_days   = 400
      force_destroy = true
    }
    alb-logs = {
      # SSE-S3, not SSE-KMS. ALB access-log delivery does not support a
      # customer-managed CMK; pointing it at a KMS-encrypted bucket does not
      # error, log delivery just silently stops — destroying the very audit
      # trail threat model T8.4 depends on. Isolated in its own bucket so the
      # KMS requirement holds everywhere else. Recorded in ADR-003 + scar log.
      # Tag VALUES are stricter than security-group descriptions: S3 allows only
      # letters, digits, whitespace and + - = . _ : / @ — no parentheses or
      # semicolons. Keep the prose here in the comment, not in the tag.
      purpose       = "ALB access logs SSE-S3 per ADR-003 exception"
      kms           = false
      transition_ia = 30
      expire_days   = 400
      force_destroy = true
    }
    backups = {
      purpose       = "Database exports and backups"
      kms           = true
      transition_ia = null
      expire_days   = 35
      force_destroy = true
    }
    evidence = {
      purpose = "Graded capstone evidence"
      kms     = true
      # No expiry: these are graded artifacts. Deleting them is a deliberate
      # act, never a lifecycle rule quietly ageing them out before G5.
      transition_ia = null
      expire_days   = null
      force_destroy = false
    }
  }
}

resource "aws_s3_bucket" "this" {
  for_each = local.buckets

  bucket        = "${var.name_prefix}-${each.key}-${var.account_id}"
  force_destroy = each.value.force_destroy

  tags = {
    Name    = "${var.name_prefix}-${each.key}"
    purpose = each.value.purpose
  }
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = local.buckets

  bucket = aws_s3_bucket.this[each.key].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = each.value.kms ? "aws:kms" : "AES256"
      kms_master_key_id = each.value.kms ? var.kms_key_arn : null
    }
    bucket_key_enabled = each.value.kms
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each = aws_s3_bucket.this

  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  # Evidence has no lifecycle rules at all — skip it rather than write a rule
  # that does nothing, so a future edit cannot accidentally give it an expiry.
  for_each = { for k, v in local.buckets : k => v if v.expire_days != null }

  bucket = aws_s3_bucket.this[each.key].id

  rule {
    id     = "retention"
    status = "Enabled"

    filter {}

    dynamic "transition" {
      for_each = each.value.transition_ia == null ? [] : [each.value.transition_ia]
      content {
        days          = transition.value
        storage_class = "GLACIER_IR"
      }
    }

    expiration {
      days = each.value.expire_days
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# ---------------------------------------------------------------------------
# Bucket policies
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "deny_insecure" {
  for_each = aws_s3_bucket.this

  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions   = ["s3:*"]
    resources = [each.value.arn, "${each.value.arn}/*"]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

# ALB log delivery needs an explicit grant. Keep the write scope at the exact
# prefix AWS uses for this account's access logs. The service principal is the
# current AWS recommendation; us-west-1 also supports the legacy regional ELB
# account, so include it for compatibility in this older region.
data "aws_iam_policy_document" "alb_logs" {
  source_policy_documents = [data.aws_iam_policy_document.deny_insecure["alb-logs"].json]

  statement {
    sid    = "AllowModernAlbLogDelivery"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["logdelivery.elasticloadbalancing.amazonaws.com"]
    }

    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.this["alb-logs"].arn}/alb/AWSLogs/${var.account_id}/*"]

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
  }

  dynamic "statement" {
    for_each = local.legacy_elb_log_delivery_account_id == null ? [] : [local.legacy_elb_log_delivery_account_id]

    content {
      sid    = "AllowLegacyAlbLogDelivery"
      effect = "Allow"

      principals {
        type        = "AWS"
        identifiers = ["arn:aws:iam::${statement.value}:root"]
      }

      actions   = ["s3:PutObject"]
      resources = ["${aws_s3_bucket.this["alb-logs"].arn}/alb/AWSLogs/${var.account_id}/*"]
    }
  }
}

resource "aws_s3_bucket_policy" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id
  policy = each.key == "alb-logs" ? data.aws_iam_policy_document.alb_logs.json : data.aws_iam_policy_document.deny_insecure[each.key].json

  depends_on = [aws_s3_bucket_public_access_block.this]
}
