# envs/dev

The dev root module. See [`../../README.md`](../README.md) for how to run it.

## Required input

Only one: `kms_key_arn`, from the bootstrap stack.

```bash
terraform -chdir=../../bootstrap output -raw kms_key_arn
```

Everything else has a defensible default. Copy `terraform.tfvars.example` to
`terraform.tfvars` (gitignored) and fill in the key ARN.

## Before the first apply

**Verify the availability zones.** The default is `["us-west-1a","us-west-1c"]`.
Confirm the target account supports those zones before applying:

```bash
aws ec2 describe-availability-zones --region us-west-1 \
  --query 'AvailabilityZones[?State==`available`].ZoneName' --output text
```

If this environment moves to another AWS account, re-run the command and update
the pinned AZ list before applying.

## Before G4

Two accepted risks have to be closed before any drill that claims resilience:

```hcl
db_multi_az       = true   # AR-2
nat_gateway_count = 2      # AR-1
```

Both are single-variable changes by design.
