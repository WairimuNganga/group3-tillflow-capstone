# infra

Owner: **Lwam (Platform)**. All AWS infrastructure is Terraform-managed —
console changes earn no evidence credit and show up as plan drift.

```
infra/
├── bootstrap/      run ONCE per account: state bucket, lock table, CMK, OIDC role
├── modules/        reusable building blocks
├── envs/dev/       the only root module today
└── scripts/        bootstrap / deploy / destroy wrappers + the naming-tag audit
```

## First run

The bootstrap stack creates the backend everything else uses, so it cannot use
that backend itself. It runs with local state, once.

```bash
# 0. Verify the account AZs before the first apply.
aws ec2 describe-availability-zones --region us-west-1 \
  --query 'AvailabilityZones[?State==`available`].ZoneName' --output text

# 1. Backend + OIDC role
./infra/scripts/bootstrap.sh

# 2. Wire the outputs into envs/dev/backend.tf and terraform.tfvars
cp infra/envs/dev/terraform.tfvars.example infra/envs/dev/terraform.tfvars
# set kms_key_arn from the bootstrap output

# 3. Plan (also runs fmt, validate, test and the naming/tag audit)
./infra/scripts/deploy.sh

# 4. Apply
./infra/scripts/deploy.sh --apply
```

Teardown for the G5 destroy/rebuild proof: `./infra/scripts/destroy.sh`.
It deliberately leaves `bootstrap/` alone — the state bucket must outlive the
environment it tracks.

## Checks that run without AWS credentials

```bash
terraform fmt -check -recursive infra/
terraform -chdir=infra/envs/dev init -backend=false && terraform -chdir=infra/envs/dev validate
terraform -chdir=infra/envs/dev test    # architecture contracts via mock_provider
```

`terraform test` is the naming/tag audit and the architecture contract in one.
It asserts the ALB is internal, exactly two distinct AZs, one SG per service,
**only `payments` has internet egress**, two containers per task (app + ADOT),
ECR/log-group/cluster naming, and that `latest` and the fake adapter are
rejected outright. It runs on every PR.

## Design notes worth knowing before you edit

**The VPC Link security group lives in `envs/dev/main.tf`, not in a module.**
The ALB must allow it as ingress while API Gateway must reference the ALB's
listener — a dependency cycle if either module owned it.

**Secret resource policies are root-level resources**, for the same reason:
they name the task roles allowed to read each secret, and those roles are
created by modules that consume the secret ARNs. Terraform builds its graph
from config references, so a conditional does not break that cycle.

**`attach_to_alb` is an explicit boolean**, not a null-check on the ALB's SG
id. `count` must resolve at plan time and the id is unknown until apply.

**Only `payments` gets `allow_internet_egress = true`.** It is the one service
that talks to Daraja. The rule it creates is 443-to-anywhere, not a Daraja
allow-list — security groups filter by CIDR, not hostname, and Daraja publishes
no stable range. That residual is accepted as **AR-7** in the threat model and
watched via VPC flow logs; do not describe it as "Daraja-only egress".

**ALB access logs go to their own SSE-S3 bucket.** ALB log delivery does not
support a customer-managed KMS key, and pointing it at the KMS-encrypted logs
bucket does not error — delivery just silently stops. See the ADR-003
exception and `docs/scar-log.md`.

Backed by [ADR-001](../docs/adr/ADR-001-aws-region.md) (region),
[ADR-002](../docs/adr/ADR-002-database.md) (database),
[ADR-003](../docs/adr/ADR-003-object-storage.md) (object storage),
[ADR-009](../docs/adr/ADR-009-ci-cd-promotion-and-rollback.md) (CI/CD),
[ADR-010](../docs/adr/ADR-010-networking-topology.md) (networking),
and `docs/threat-model.md`.
