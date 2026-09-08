# Threat Model — TillFlow (devops-g3)

- **Status:** Accepted (G0)
- **DRI:** Lwam
- **Date:** 2026-09-08
- **Review cadence:** re-reviewed at every gate (G1–G5); any new trust boundary, new inbound
  endpoint, or new secret requires an update in the **same PR** that introduces it.

## Scope and method

TillFlow is a multi-tenant POS that takes customer money through an M-Pesa till (STK Push) and pays
attendant commissions out through M-Pesa B2C. It therefore holds three things worth attacking:
**money movement**, **tenant-scoped business data**, and **payment-provider credentials**.

Method: enumerate the assets, draw the trust boundaries from
[`architecture.md`](architecture.md) and [ADR-010](adr/ADR-010-networking-topology.md), then apply
**STRIDE** at each boundary. Every threat gets a mitigation with an owner and a piece of evidence
that proves the mitigation exists — a mitigation with no proof is treated as an accepted risk, not
as a control.

Environment scope: Daraja **sandbox only** ([ADR-007](adr/ADR-007-m-pesa-adapter.md)). No real
customer money and no real customer PII ever enters this system. That materially lowers the impact
of most confidentiality threats below, but it does **not** change the design — the controls are
built as if the data were real, because the point of the exercise is a production-grade posture.

## Assets and data classification

| Asset | Class | Where it lives | Impact if compromised |
|---|---|---|---|
| Daraja consumer key/secret, passkey, initiator credential | **Secret** | Secrets Manager (`devops-g3/daraja`) | Attacker can initiate STK/B2C as us — direct financial loss |
| DB credentials (per-service roles) | **Secret** | Secrets Manager (`devops-g3/db`), consumed via RDS Proxy | Full read/write of all tenants' data |
| Slack webhook URL | **Secret** | Secrets Manager (`devops-g3/slack-webhook`) | Alert-channel spoofing / spam; erodes trust in real alerts |
| Terraform state | **Secret** (contains resource identifiers + any leaked attribute) | `tillflow-tfstate-<account_id>`, SSE-KMS, versioned ([ADR-003](adr/ADR-003-object-storage.md)) | Infrastructure map; corruption blocks all deploys |
| Attendant + customer MSISDNs (phone numbers) | **PII** | RDS `payments`/`commission` schemas | Personal data disclosure; regulatory exposure in a real deployment |
| Sale, payment, and payout ledger rows | **Confidential, integrity-critical** | RDS, tenant-scoped | Wrong money state; unrecoverable if integrity is lost silently |
| Tenant configuration (till number, commission rates, roles) | **Confidential** | RDS `web`/`pos` schemas | Commission-rate tampering = financial loss, quietly |
| Container images in ECR | **Integrity-critical** | ECR, SHA-tagged ([ADR-009](adr/ADR-009-ci-cd-promotion-and-rollback.md)) | Arbitrary code in the money path |
| Telemetry (traces, logs, metrics) | **Confidential** (may leak PII if unredacted) | AMP, CloudWatch Logs, X-Ray, Grafana | Secondary PII leak path; the one people forget |
| Evidence bucket | **Confidential** | `tillflow-evidence-<account_id>` | Graded artifacts; also a place PII could accidentally be parked |

**PII rule (binding on all services):** MSISDNs are stored in the database only where a payment
genuinely requires them, and are **never** written to a log line, span attribute, metric label, k6
output, or evidence artifact in raw form. The shared OTel/logging wrapper in `services/_shared`
redacts to a last-3-digit-masked form (`+2547*****123`) before anything leaves the process — this is
central, not per-service discipline ([ADR-008](adr/ADR-008-telemetry-conventions.md)). A service
cannot "forget" to redact, because it never hands the raw value to the telemetry call.

## Trust boundaries

```
                    ┌── TB1 ── public internet edge
 attendant/browser ─┼─► API Gateway (HTTP API)
                    │        │
                    │   TB2 ─┴─► VPC Link ──► internal ALB ──► ECS Fargate (app private subnets)
                    │                                            │   ├─ web
                    │                                            │   ├─ pos      ┐
                    │                                            │   ├─ payments ├─ TB3 service↔service
                    │                                            │   └─ commission┘
                    │                                            │
                    │                                       TB4 ─┴─► RDS (data subnets, no egress)
                    │                                                Redis · SQS/DLQ · S3 · Secrets Mgr
 Safaricom Daraja ──┴── TB5 ── unauthenticated inbound callback ──► payments /callback/<secret-path>
                                                                          │
 developer / GitHub Actions ── TB6 ── OIDC ──► AWS (Terraform, ECS deploy)│
 base images + npm/pip deps ── TB7 ── build ──► ECR ──────────────────────┘
 operator ── TB8 ──► Grafana / CloudWatch Logs / X-Ray (telemetry read path)
```

**TB5 is the sharpest boundary in the system.** It is the only place where an unauthenticated party
on the public internet POSTs a message that directly changes money state. Everything about the
payments callback handler is designed around the assumption that the caller is *not* proven to be
Safaricom.

## Threats and mitigations (STRIDE per boundary)

### TB1 — Internet → API Gateway

| # | STRIDE | Threat | Mitigation | Owner | Proof |
|---|---|---|---|---|---|
| T1.1 | Spoofing | Unauthenticated caller hits POS/payments APIs directly | All non-callback routes require an authenticated, tenant-scoped session; API Gateway is the only public entry, ALB is internal-only ([ADR-010](adr/ADR-010-networking-topology.md)) | Lwam / Joyce | `terraform plan` showing internal ALB + no public listener |
| T1.2 | Tampering | Credentials or sale payloads read/modified in transit | TLS 1.2+ terminated at API Gateway; no plaintext listener anywhere | Lwam | API Gateway TLS policy in plan |
| T1.3 | Denial of service | Request flood exhausts ECS tasks and burns the error budget | API Gateway throttling (per-route burst/rate limits) + ECS service autoscaling; k6 spike test establishes the sustainable envelope | Minage | k6 spike JSON + throttle config |
| T1.4 | Elevation | Attendant-role token used against owner-only tenant-config routes | Tenant-scoped RBAC checked in the API layer *and* re-checked server-side per route — never trusted from a client-supplied role claim alone | Joyce | authz test suite |

### TB2 — API Gateway → VPC Link → internal ALB → ECS

| # | STRIDE | Threat | Mitigation | Owner | Proof |
|---|---|---|---|---|---|
| T2.1 | Spoofing | Something inside the VPC calls the ALB directly, bypassing the gateway's authn/throttling | ALB SG accepts inbound 443 **only** from the VPC Link ENIs; per-service SGs accept only from the ALB SG on that service's port | Lwam | SG rules in `terraform plan` |
| T2.2 | Information disclosure | Task or DB reachable from the internet | No public IP on any ECS task or RDS instance; data subnets have **no route** to NAT or IGW at all | Lwam | route tables in plan |
| T2.3 | Tampering | Compromised container writes to its own filesystem to persist | Containers run **non-root** with a **read-only root filesystem**; writable paths limited to explicit tmpfs mounts | Wairimu | task definition JSON |

### TB3 — Service ↔ service

| # | STRIDE | Threat | Mitigation | Owner | Proof |
|---|---|---|---|---|---|
| T3.1 | Elevation | `commission` calls Daraja B2C directly, bypassing the payments service's idempotency and ledger invariants | Architectural rule: **only `payments` holds Daraja credentials**. The `devops-g3/daraja` secret's resource policy and the task-role IAM policies grant `secretsmanager:GetSecretValue` on it to the `payments` task role *only* — `commission` is technically unable to call Daraja even if someone writes the code | Lwam / Hunter | IAM policy in plan; the brief blocks G2 on exactly this |
| T3.2 | Spoofing | Unauthorized internal caller invokes `payments`' B2C endpoint | Internal calls carry a service identity; the B2C route is not exposed through API Gateway at all (internal ALB path only) + SG-level restriction to the calling service's SG | Hunter | route map + SG rules |
| T3.3 | Repudiation | No way to attribute who triggered a payout | Every money-path span carries `tenant_id` + `idempotency_key` at 100% sampling; structured JSON logs carry `trace_id`/`span_id` ([ADR-008](adr/ADR-008-telemetry-conventions.md)) | Minage | trace capture in `evidence/` |

### TB4 — Service → data plane

| # | STRIDE | Threat | Mitigation | Owner | Proof |
|---|---|---|---|---|---|
| T4.1 | Information disclosure | **Cross-tenant data leak** via a missing `WHERE tenant_id = ?` | Postgres **RLS** on every tenant-owned table, `SET LOCAL app.current_tenant_id` per transaction, `BYPASSRLS` revoked on every service role including the owner ([ADR-005](adr/ADR-005-multi-tenancy-isolation.md)) | Joyce | RLS cross-tenant isolation test suite |
| T4.2 | Elevation | One service reads or writes another service's schema | Schema-per-service with least-privilege roles; cross-service reads only through explicit read-only views, never raw table grants ([ADR-002](adr/ADR-002-database.md)) | Lwam | `\dp` grant dump + plan |
| T4.3 | Tampering | Injection through sale line items or callback payload | Parameterized queries only (no string-built SQL); schema validation at the API boundary before anything reaches the DB layer | Joyce / Hunter | integration + fuzz-ish contract tests |
| T4.4 | Information disclosure | Data readable at rest by anyone with storage access | SSE-KMS on all five S3 buckets (shared CMK, rotation on, BPA at bucket **and** account level), RDS storage encryption, Redis encryption in transit + at rest ([ADR-003](adr/ADR-003-object-storage.md)) | Lwam | bucket policies + RDS config |
| T4.5 | Information disclosure | Cache poisoning / cross-tenant cache read in Redis | Every cache key is prefixed with `tenant_id`; no unkeyed global caches on tenant-scoped data | Joyce | key-naming convention + test |
| T4.6 | Denial of service | One tenant's or one service's runaway query starves the shared RDS instance | RDS Proxy per-credential connection limits; single-instance blast radius is a **known accepted risk** (AR-2 below) | Lwam | proxy config; [ADR-002](adr/ADR-002-database.md) consequences |

### TB5 — Daraja callback (the sharp edge)

| # | STRIDE | Threat | Mitigation | Owner | Proof |
|---|---|---|---|---|---|
| T5.1 | Spoofing | **Forged callback** marks an unpaid sale as paid — free goods, and a commission payout on money never received | Daraja sandbox does not sign callbacks, so authenticity is established by defense in depth: (a) unguessable per-tenant secret path segment in the registered callback URL, held in Secrets Manager, rotated, and **never logged** (the redaction wrapper strips it from request-path log fields); (b) the callback body is treated as a *hint*, not as truth — settlement above a configurable amount threshold, or any payload inconsistent with the stored `CheckoutRequestID`, is confirmed via `queryTransactionStatus` against Daraja before the ledger is written ([ADR-007](adr/ADR-007-m-pesa-adapter.md)) | Hunter | forged-callback rejection test + trace |
| T5.2 | Tampering | Replayed or reordered callback produces a second ledger effect | Upsert on the unique `(MerchantRequestID, CheckoutRequestID)` pair; duplicate is a no-op on conflict; the state machine permits exactly one legal transition ([ADR-004](adr/ADR-004-idempotency-and-money-integrity.md)) | Hunter | replay/reorder invariant tests — also a G4 drill |
| T5.3 | Tampering | Amount in the callback differs from the amount of the sale it claims to settle | Amount is compared against the stored sale total (integer minor units, converted through the single shared whole-shilling function) before settlement; mismatch → do not settle, flag for reconciliation | Hunter | conversion + mismatch unit tests |
| T5.4 | Denial of service | Callback endpoint flooded, or Daraja goes silent entirely | Endpoint is throttled and rate-limited independently of the main API; a **timeout is never a decline** — the sale stays `pending` and the reconciliation worker resolves it from Daraja's authoritative status query, with SQS + DLQ making stuck work visible rather than silently dropped | Hunter / Minage | DLQ-depth alarm + forced-timeout drill |
| T5.5 | Repudiation | "We were double-charged" with no way to prove otherwise | 100% trace sampling on the money path; the full `pending → pending_reconciliation → resolved` path is reconstructible from a single `trace_id` | Minage | captured trace |
| T5.6 | Elevation | Callback path used to reach non-callback functionality | The callback route is narrowly scoped: it accepts one payload shape, performs no tenant-role resolution from the body, and cannot create tenants, sales, or payouts — only transition an existing payment | Hunter | route contract test |

### TB6 — Developer / CI → AWS

| # | STRIDE | Threat | Mitigation | Owner | Proof |
|---|---|---|---|---|---|
| T6.1 | Spoofing | Leaked long-lived AWS access keys used to deploy | **No static AWS keys anywhere.** GitHub Actions assumes `devops-g3-ci-deploy` via **OIDC**, with the trust policy's `sub` condition scoped to this repository and the `main` ref — a fork or another repo cannot assume it | Wairimu | trust policy JSON + successful OIDC run |
| T6.2 | Elevation | CI role is effectively admin | CI deploy role is scoped to the resources it actually touches (ECR push, ECS update-service, the Terraform-managed resource set) — no `*:*`; `terraform plan` on PR runs under a **read-only** role, `apply` only from `main` behind a protected environment ([ADR-009](adr/ADR-009-ci-cd-promotion-and-rollback.md)) | Wairimu / Lwam | IAM policy + protected-environment config |
| T6.3 | Information disclosure | A secret is committed, or printed into build logs / Terraform state | Secret scanning as a required PR check; secrets referenced by **ARN** in Terraform and injected by ECS at task start (`secrets` block), never passed as Terraform variables or plaintext env values; `.gitignore` covers `*.tfvars`, `*.tfstate`; state bucket is SSE-KMS + versioned + BPA | Wairimu / Lwam | scan job output + task definition showing ARN references only |
| T6.4 | Tampering | Unreviewed code reaches `main` and deploys | Branch protection: PR required, **CODEOWNERS review required**, `validate` + scan set as required status checks. Every path has exactly one DRI in `CODEOWNERS` | Wairimu | branch-protection settings + CODEOWNERS |
| T6.5 | Repudiation | Console click-ops changes infrastructure with no record | Everything is Terraform-managed; console changes earn no evidence credit and show up as plan drift. Drift is checked before each gate | Lwam | clean `terraform plan` at gate time |

### TB7 — Supply chain (base images + dependencies → ECR → ECS)

| # | STRIDE | Threat | Mitigation | Owner | Proof |
|---|---|---|---|---|---|
| T7.1 | Tampering | Malicious or vulnerable transitive dependency ships to production | Dependency scanning + **SBOM generation** per build; pipeline **fails on fixable HIGH/CRITICAL**; unfixable findings are logged as accepted risk with an owner and expiry in [`scar-log.md`](scar-log.md), never silently passed ([ADR-009](adr/ADR-009-ci-cd-promotion-and-rollback.md)) | Wairimu | SBOM + scan report in `evidence/delivery/` |
| T7.2 | Tampering | Base image swapped underneath us between builds | Base images **pinned by digest**, not by floating tag; multi-stage build so build tooling never ships in the runtime layer | Wairimu | Dockerfile + build log |
| T7.3 | Spoofing | Ambiguity about which artifact is actually running | No `latest` tag ever; build by commit SHA, deploy the **immutable digest**, expose commit + digest at runtime (`/healthz`) and in pipeline evidence | Wairimu | runtime `/healthz` output vs pipeline log |
| T7.4 | Tampering | IaC misconfiguration introduces a public bucket or open SG | IaC scanning as a required PR check, in addition to human CODEOWNERS review | Wairimu | scan job output |
| T7.5 | Elevation | An old vulnerable image is redeployed during a rollback | ECR enhanced scanning on push; ECR lifecycle policy keeps a **minimum retention count** so rollback targets exist, and rollback targets are known-good SHAs, not arbitrary old ones | Wairimu | ECR scan findings + lifecycle policy |

### TB8 — Telemetry and operations (the leak path people forget)

| # | STRIDE | Threat | Mitigation | Owner | Proof |
|---|---|---|---|---|---|
| T8.1 | Information disclosure | Raw MSISDNs, callback secret paths, or Daraja tokens end up in logs, spans, metric labels, k6 output, or a screenshot in `evidence/` | Central redaction in the `services/_shared` telemetry wrapper (see PII rule above); no secret or MSISDN is ever a metric **label** (labels are high-cardinality-visible and land in AMP); evidence artifacts are reviewed for PII before commit | Minage / Lwam | redaction unit tests + a log/trace sample in `evidence/` |
| T8.2 | Spoofing | Slack webhook leaks; attacker posts fake "recovered" alerts and hides a real incident | `SLACK_WEBHOOK_URL` lives in Secrets Manager only — never in Git, Terraform state, or build logs; rotated if ever exposed. Alerts carry a Grafana panel link so a claim can be checked against the actual signal, not believed on its own | Minage | secret ARN reference + firing/recovery evidence |
| T8.3 | Information disclosure | Self-hosted Grafana ([ADR-001](adr/ADR-001-aws-region.md)) exposed publicly or left on default `admin:admin` | Grafana runs in the private app subnets behind the same internal-ALB pattern as every other service, with the admin credential in Secrets Manager and anonymous access disabled | Lwam / Minage | task definition + SG rules |
| T8.4 | Repudiation | ALB access logs, the audit trail for edge traffic, are missing or mutable | ALB access logging enabled to `tillflow-logs-<account_id>`; bucket is versioned, SSE-KMS, BPA, 400-day retention ([ADR-003](adr/ADR-003-object-storage.md)) | Lwam | bucket policy + sample log objects |

## Accepted risks

Each has an owner and an expiry. On expiry it is either fixed or explicitly re-accepted in a PR —
"it's been like that for a while" is not a re-acceptance. Anything that actually bites us gets
logged in [`scar-log.md`](scar-log.md) as it happens.

| ID | Risk | Why accepted | Owner | Expiry / trigger |
|---|---|---|---|---|
| AR-1 | **Single NAT Gateway in `dev`** — one point of egress failure; loses Daraja reachability for the whole VPC ([ADR-010](adr/ADR-010-networking-topology.md)) | Cost, in a region already more expensive than `us-west-2` | Lwam | Upgrade to one-per-AZ **before any G4 drill that claims AZ-independent egress** |
| AR-2 | **Single-AZ, single-instance RDS in `dev`** — shared blast radius, and an AZ loss is an outage ([ADR-002](adr/ADR-002-database.md)) | Cost; capstone-scale load | Lwam | Multi-AZ standby **before G4** |
| AR-3 | **Daraja sandbox callbacks are unsigned** — authenticity rests on a secret URL path + status re-query rather than a cryptographic signature | Safaricom's sandbox provides no signing mechanism; not ours to fix | Hunter | Permanent for this capstone; a real deployment would require IP allow-listing of Safaricom's callback ranges + mTLS if offered |
| AR-4 | **One shared KMS CMK across all five S3 buckets** — compromise of the key affects all five ([ADR-003](adr/ADR-003-object-storage.md)) | Per-bucket CMK overhead not justified at this scale | Lwam | Revisit if any bucket takes on genuinely different-sensitivity data |
| AR-5 | **10% trace sampling on `pos`/`web`** — a specific non-error request may have no trace during an investigation | Volume/cost; always-sample-on-error keeps real failures traceable ([ADR-008](adr/ADR-008-telemetry-conventions.md)) | Minage | Revisit if an incident is materially delayed by a missing trace |
| AR-6 | **No WAF in front of API Gateway** | Cost and setup time against a sandbox-only workload with no real customer data | Lwam | Re-evaluate at G3 if the k6 spike test or logs show abusive traffic patterns |

## Explicitly out of scope

- **Real Daraja production credentials and real customer money** — sandbox only, by the brief.
- **Physical/endpoint security of attendant devices** — a compromised till device is assumed out of
  our control; the mitigation we *do* own is that a stolen session is tenant- and role-scoped
  (T1.4) and cannot reach Daraja directly (T3.1).
- **Insider threat from a team member with legitimate `main` access** — mitigated only to the extent
  that CODEOWNERS review + Terraform-only changes leave an audit trail (T6.4, T6.5).
- **Compliance certification** (PCI-DSS, Kenya DPA registration) — a real deployment would need
  both; not assessed here.

## Required proof (from the brief)

Filed under `evidence/platform/` unless noted, with exact reproduction commands:

1. **Forged-callback rejection** — a request to the payments callback route with a wrong/absent
   secret path segment is rejected and writes no ledger row (`evidence/payments/`).
2. **Replay safety** — duplicate and out-of-order callbacks produce exactly one ledger effect
   ([ADR-004](adr/ADR-004-idempotency-and-money-integrity.md) invariant tests, `evidence/payments/`).
3. **Cross-tenant isolation** — RLS test suite showing tenant B's rows are absent (not merely
   forbidden) from tenant A's query ([ADR-005](adr/ADR-005-multi-tenancy-isolation.md)).
4. **No static AWS keys** — the OIDC trust policy JSON for `devops-g3-ci-deploy`, plus a successful
   run log showing credentials assumed via OIDC (`evidence/delivery/`).
5. **Secrets never in Git or logs** — secret-scan job output, plus a task definition showing
   Secrets Manager **ARN** references only.
6. **PII redaction** — a captured log line and span for a real payment showing masked MSISDNs
   (`evidence/reliability/`).
7. **Least-privilege IAM** — `terraform plan` output for the task roles, specifically showing that
   only the `payments` task role can read `devops-g3/daraja`.
8. **Network posture** — `terraform plan` showing internal-only ALB, no public IPs, and data subnets
   with no NAT/IGW route.
9. **Supply chain** — SBOM + dependency/IaC/ECR scan reports with the HIGH/CRITICAL gate enforced
   (`evidence/delivery/`).
