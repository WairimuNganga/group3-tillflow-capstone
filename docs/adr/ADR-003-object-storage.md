# ADR-003: Object storage (S3)

- **Status:** Accepted
- **DRI:** Lwam
- **Date:** 2026-09-08

## Context
Five distinct purposes need object storage with different lifecycle, retention, and access needs:
Terraform state, build artifacts, logs, backups, and grading/drill evidence. Names must be globally
unique, and the state bucket needs a companion lock to support five people running Terraform
concurrently.

## Decision
One bucket per purpose, named `devops-g3-<purpose>-<account_id>` (lowercase, account-ID suffix for
global uniqueness):

| Bucket | Versioning | Encryption | Public access | Lifecycle |
|---|---|---|---|---|
| `devops-g3-tfstate-<account_id>` | On | SSE-KMS (shared CMK, bucket keys on) | Blocked | Noncurrent versions expire after 90d; current version never expires |
| `devops-g3-artifacts-<account_id>` | On | SSE-KMS | Blocked | → Glacier IR at 30d, expire at 180d |
| `devops-g3-logs-<account_id>` | On | SSE-KMS | Blocked | → Glacier IR at 30d, expire at 400d (>1yr audit trail) |
| `devops-g3-backups-<account_id>` | On | SSE-KMS | Blocked | Expire at 35d (matches RDS's 7-day retention with margin) |
| `devops-g3-evidence-<account_id>` | On | SSE-KMS | Blocked | No automatic expiration — these are graded artifacts |
| `devops-g3-alb-logs-<account_id>` | On | **SSE-S3 (AES256)** — see exception below | Blocked | → Glacier IR at 30d, expire at 400d |

All buckets except the ALB log bucket share one customer-managed KMS key (`alias/devops-g3-s3`,
rotation enabled) — adequate isolation at this scale via IAM key-policy scoping of who can
`Decrypt`, without paying per-bucket KMS overhead. Block Public Access is enabled at both the
bucket and account level.

### Exception: ALB access logs use SSE-S3, not SSE-KMS

Application Load Balancer access-log delivery does not support buckets encrypted with a
customer-managed KMS key; only SSE-S3 (AES256) is supported. Applying the shared CMK to the bucket
ALB writes to would not fail loudly — **log delivery would simply stop**, destroying the edge audit
trail that `docs/threat-model.md` T8.4 depends on, with no error surfaced at apply time.

Rather than weaken the shared `devops-g3-logs` bucket to AES256 for every producer, ALB logs go to
their own bucket, `devops-g3-alb-logs-<account_id>`, encrypted SSE-S3. Every other bucket keeps the
KMS requirement. The tradeoff accepted: objects in this one bucket are not protected by a
key policy, so access control rests entirely on the bucket policy and IAM — which is why it stays
versioned, BPA-blocked, and write-only for the ALB log-delivery principal.

Recorded as a deviation in [`scar-log.md`](../scar-log.md). Flagged by mentor feedback at G0.

The state bucket is paired with a DynamoDB lock table, `devops-g3-tflock` (`LockID` partition
key, `PAY_PER_REQUEST` billing), referenced by every `infra/envs/*` root module's S3 backend block.

## Alternatives considered
- **One shared bucket with purpose-prefixes** — rejected: different lifecycle/versioning/retention
  rules per purpose are cleaner as separate bucket policies, and it keeps a policy mistake on one
  purpose from exposing another (e.g., a logs lifecycle mistake can't touch evidence).
- **Local or unlocked remote Terraform state** — rejected: five people applying concurrently without
  a lock table will corrupt state.
- **Per-service buckets instead of per-purpose** — rejected for G0: 5 services × 5 purposes = 25
  buckets is unnecessary sprawl at this scale; revisit only if a service needs bucket-level IAM
  isolation the shared-CMK model can't give it.

## Consequences
- A compromise of the shared CMK affects all five buckets — mitigated by a tight key policy scoping
  `Decrypt` to the specific roles that need each bucket, not "any authenticated principal."
- The evidence bucket's no-expiration lifecycle is deliberate — don't "clean it up" before grading;
  anything actually stale should be deleted explicitly, not left to a lifecycle rule.
- The DynamoDB lock table is new shared infrastructure every teammate must know about before running
  `terraform apply` — documented in `infra/README.md` and `docs/runbook.md`.

## Required proof (from brief)
ADR + bucket policy (exported policy JSON per bucket, attached once `infra/modules/s3` is applied).
