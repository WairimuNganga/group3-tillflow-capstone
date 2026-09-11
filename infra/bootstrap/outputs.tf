output "state_bucket" {
  description = "S3 bucket holding remote state. Wire into envs/*/backend.tf."
  value       = aws_s3_bucket.tfstate.id
}

output "lock_table" {
  description = "DynamoDB table used for state locking."
  value       = aws_dynamodb_table.tflock.name
}

output "kms_key_arn" {
  description = "Shared CMK for S3 buckets and the lock table."
  value       = aws_kms_key.s3.arn
}

output "ci_deploy_role_arn" {
  description = "Role GitHub Actions assumes via OIDC. Set as AWS_DEPLOY_ROLE in the workflow."
  value       = aws_iam_role.ci_deploy.arn
}

output "ci_plan_role_arn" {
  description = "Read-only role for PR plans. Set as AWS_PLAN_ROLE_ARN in the workflow."
  value       = aws_iam_role.ci_plan.arn
}
