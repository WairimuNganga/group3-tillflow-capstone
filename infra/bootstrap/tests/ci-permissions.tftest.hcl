# CI deploy-role permission contract, verified with a mocked AWS provider.
#
#   cd infra/bootstrap && terraform test
#
# Why this file exists: a missing permission on devops-g3-ci-deploy does not
# fail the plan. It fails mid-apply, after Terraform has already created
# whatever came earlier in the graph, leaving the stack half-built. That has
# happened three times -- rds:CreateSecret, ecs:TagResource, and most recently
# lambda:CreateFunction for the Slack alarm relay, which left an orphaned log
# group and IAM role in the account with no function attached.
#
# Assertions here are on config-derived locals, not on rendered policy JSON:
# aws_iam_policy_document mocks to an empty document under `terraform test`, so
# a JSON assertion would pass against nothing.

mock_provider "aws" {
  override_during = plan

  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "240462142849"
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

variables {
  region            = "us-west-1"
  name_prefix       = "devops-g3"
  owner             = "platform"
  github_repository = "WairimuNganga/group3-tillflow-capstone"
}

run "ci_deploy_can_manage_terraform_owned_lambdas" {
  command = plan

  # The Slack relay is invoked directly by the DLQ alarms. Without this scope
  # the apply dies after the log group and role are created.
  assert {
    condition = contains(
      output.ci_deploy_lambda_function_arns,
      "arn:aws:lambda:us-west-1:240462142849:function:devops-g3-slack-alarm"
    )
    error_message = "The CI deploy role must be able to manage the devops-g3-slack-alarm function, or a GitHub apply fails partway and leaves an orphaned log group and IAM role."
  }

  # Least privilege: the synthetics statement is deliberately scoped to
  # `cwsyn-*`, and this one to an exact function name. A prefix wildcard here
  # would silently authorise every future Lambda in the account.
  assert {
    condition = alltrue([
      for arn in output.ci_deploy_lambda_function_arns :
      !endswith(arn, "*")
    ])
    error_message = "Terraform-owned Lambda grants must name the function exactly. A `devops-g3-*` wildcard would authorise functions nobody reviewed."
  }

  # Every entry must be a Lambda function ARN in this account and region --
  # a malformed ARN yields a grant that silently matches nothing.
  assert {
    condition = alltrue([
      for arn in output.ci_deploy_lambda_function_arns :
      startswith(arn, "arn:aws:lambda:${var.region}:240462142849:function:${var.name_prefix}-")
    ])
    error_message = "Lambda grants must be function ARNs in this account/region and carry the group name prefix."
  }
}
