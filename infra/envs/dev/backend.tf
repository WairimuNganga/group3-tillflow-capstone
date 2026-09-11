# Remote state, created by infra/bootstrap. The bucket name embeds the account
# ID (S3 names are globally unique) and the DynamoDB table serialises applies
# so five people cannot corrupt state by running at once (ADR-003).
terraform {
  backend "s3" {
    bucket         = "devops-g3-tfstate-240462142849"
    key            = "envs/dev/terraform.tfstate"
    region         = "us-west-1"
    dynamodb_table = "devops-g3-tflock"
    encrypt        = true
  }
}
