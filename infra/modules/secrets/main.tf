# Secrets Manager entries. Terraform creates the *containers* and their ARNs;
# it never sets a value. Values are populated out-of-band (console or CLI) by
# whoever holds them, so no credential ever passes through Terraform state,
# a plan output, or a build log (threat model T6.3, brief's secrets rule).
#
# After apply, populate with:
#   aws secretsmanager put-secret-value --secret-id devops-g3/daraja \
#     --secret-string file://daraja.json   # then shred the file

locals {
  secrets = {
    daraja = {
      description = "Daraja sandbox: consumer key/secret, passkey, initiator credential, callback path segment"
      # Only the payments task role may read this. Enforced by the resource
      # policy below AND by the task role policy — commission is technically
      # unable to call Daraja even if someone writes the code (T3.1).
      readers = var.daraja_reader_role_arns
    }
    db = {
      description = "Per-service PostgreSQL credentials, consumed via RDS Proxy"
      readers     = var.db_reader_role_arns
    }
    slack-webhook = {
      description = "Slack incoming webhook for alerting. Never in Git, TF state, or build logs."
      readers     = var.slack_reader_role_arns
    }
  }
}

resource "aws_secretsmanager_secret" "this" {
  for_each = local.secrets

  name        = "${var.name_prefix}/${each.key}"
  description = each.value.description
  kms_key_id  = var.kms_key_arn

  # Short window in dev so a rename/recreate during G1 iteration is not blocked
  # for a week by a soft-deleted secret holding the name.
  recovery_window_in_days = var.recovery_window_in_days

  tags = { Name = "${var.name_prefix}-${each.key}" }
}

# Resource policy: an explicit allow-list of principals per secret. Belt and
# braces with the task-role policies — a secret is readable only if BOTH the
# role policy and this resource policy permit it.
data "aws_iam_policy_document" "readers" {
  for_each = { for k, v in local.secrets : k => v if length(v.readers) > 0 }

  statement {
    sid    = "AllowNamedReaders"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = each.value.readers
    }

    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = ["*"]
  }
}

resource "aws_secretsmanager_secret_policy" "this" {
  for_each = data.aws_iam_policy_document.readers

  secret_arn = aws_secretsmanager_secret.this[each.key].arn
  policy     = each.value.json
}
