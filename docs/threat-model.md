# Threat Model — TillFlow (devops-g3)

- **Status:** Draft for G0 review
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
that will prove the mitigation exists. Until that evidence has been collected, the mitigation is a
planned control rather than a verified control.

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
| Terraform state | **Sensitive** (contains resource identifiers and may contain sensitive attributes) | `devops-g3-tfstate-<account_id>`, SSE-KMS, versioned ([ADR-003](adr/ADR-003-object-storage.md)) | Infrastructure disclosure; corruption blocks deploys |
| Attendant + customer MSISDNs (phone numbers) | **PII** | RDS `payments`/`commission` schemas | Personal data disclosure; regulatory exposure in a real deployment |
| Sale, payment, and payout ledger rows | **Confidential, integrity-critical** | RDS, tenant-scoped | Wrong money state; unrecoverable if integrity is lost silently |
| Tenant configuration (till number, commission rates, roles) | **Confidential** | RDS `web`/`pos` schemas | Commission-rate tampering = financial loss, quietly |
| Container images in ECR | **Integrity-critical** | ECR, SHA-tagged ([ADR-009](adr/ADR-009-ci-cd-promotion-and-rollback.md)) | Arbitrary code in the money path |
| Telemetry (traces, logs, metrics) | **Confidential** (may leak PII if unredacted) | AMP, CloudWatch Logs, X-Ray, Grafana | Secondary PII leak path if logs or traces are not redacted |
| Evidence bucket | **Confidential** | `devops-g3-evidence-<account_id>` | Graded artifacts; may accidentally contain PII or secrets if not reviewed |

**PII rule (binding on all services):** MSISDNs are stored in the database only where a payment
genuinely requires them, and are **never** written to a log line, span attribute, metric label, k6
output, or evidence artifact in raw form. The shared OTel/logging wrapper in `services/_shared`
will provide the approved masking function (for example, `+2547*****123`) before data leaves the
process ([ADR-008](adr/ADR-008-telemetry-conventions.md)). Tests and code review must still verify
that services use the wrapper and do not log raw request bodies.

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
 Safaricom Daraja ──┴── TB5 ── public callback ──► payments callback endpoint
                                                                          │
 developer / GitHub Actions ── TB6 ── OIDC ──► AWS (Terraform, ECS deploy)│
 base images + npm/pip deps ── TB7 ── build ──► ECR ──────────────────────┘
 operator ── TB8 ──► Grafana / CloudWatch Logs / X-Ray (telemetry read path)
```

**TB5 has the highest financial risk.** A public callback can influence payment state, but the
Daraja sandbox callback does not provide enough evidence of caller identity by itself. The handler
must therefore verify the callback against the payment request already stored by TillFlow and use
Daraja's transaction-status query before final settlement when authenticity or state is uncertain.

## Production release blockers

TillFlow is a capstone system using Daraja sandbox. It must **not** be connected to real tills,
production Daraja credentials, real customer data, or real payouts while any item below remains
open:

- callback authenticity depends on sandbox limitations and has not been replaced with a
  production-approved verification design;
- RDS and NAT are single-AZ in `dev`, so an Availability Zone or NAT failure can stop the service;
- WAF/rate-limit rules, tenant isolation, least-privilege IAM, egress restriction, backup restore,
  reconciliation, and rollback have not all produced the runtime evidence listed at the end of this
  document;
- outbound network access from the app subnets is currently unrestricted (T2.4) and there is no
  account-level audit trail yet (T6.6);
- idempotency records are not tenant-scoped (M1) and the ledger has no detection invariant (M5);
  both need an [ADR-004](adr/ADR-004-idempotency-and-money-integrity.md) amendment before any real
  payout path is enabled;
- refund and reversal handling has not been proven against replay, over-refund, or wrong-tenant
  cases (M6);
- commission payout timing has not been proven against later payment reversal or refund cases (M8);
- commission rates are not effective-dated and rate changes are not audited (M9), and attendant
  payee details have no cooling-off window before they become payout-eligible (M10);
- **external reconciliation against Daraja's own records has not been built (M12)** — internal
  ledger invariants alone cannot show that our books agree with the provider's;
- critical alerts have not been fired end to end with linked runbook actions and recovery evidence
  (T8.5, T8.6);
- penetration testing, privacy review, key rotation, incident-response ownership, and production
  access controls have not been completed;
- the application still permits any fake adapter, test credential, or debug mode in a deployed
  production configuration, and does not yet fail closed on a wrong adapter (T6.7).

Closing a blocker requires a reviewed PR and reproducible evidence. A design statement alone is
not approval to go live.

## Threats and mitigations (STRIDE per boundary)

### TB1 — Internet → API Gateway

| # | STRIDE | Threat | Mitigation | Owner | Proof |
|---|---|---|---|---|---|
| T1.1 | Spoofing | Unauthenticated caller hits POS/payments APIs directly | All non-callback routes require an authenticated, tenant-scoped session; API Gateway is the only public entry, ALB is internal-only ([ADR-010](adr/ADR-010-networking-topology.md)) | Lwam / Joyce | `terraform plan` showing internal ALB + no public listener |
| T1.2 | Tampering | Credentials or sale payloads read/modified in transit | Require HTTPS at the public API Gateway endpoint. Restrict the private hop with VPC Link and security groups; document and test end-to-end TLS separately if adopted | Lwam | API Gateway configuration + network test |
| T1.3 | Denial of service | Request flood exhausts ECS tasks and burns the error budget | API Gateway throttling (per-route burst/rate limits) + ECS service autoscaling; k6 spike test establishes the sustainable envelope | Minage | k6 spike JSON + throttle config |
| T1.4 | Elevation | Attendant-role token used against owner-only tenant-config routes | Tenant-scoped RBAC checked in the API layer *and* re-checked server-side per route — never trusted from a client-supplied role claim alone | Joyce | authz test suite |
| T1.5 | Spoofing | Stolen or forged session is used as an attendant or tenant owner | Short-lived signed tokens, issuer/audience validation, secure cookie settings where cookies are used, logout/revocation strategy, and no tenant identity accepted directly from request data | Joyce | authentication and cross-tenant tests |
| T1.6 | Tampering | XSS or CSRF causes an authenticated user to submit an unwanted sale or configuration change | Output encoding and CSP for the web client; CSRF protection for cookie-authenticated state-changing requests; restrictive CORS | Joyce | browser security tests + response headers |

### TB2 — API Gateway → VPC Link → internal ALB → ECS (inbound path and task egress)

| # | STRIDE | Threat | Mitigation | Owner | Proof |
|---|---|---|---|---|---|
| T2.1 | Spoofing | Something inside the VPC calls the ALB directly, bypassing the gateway's authn/throttling | ALB SG accepts inbound 443 **only** from the VPC Link ENIs; per-service SGs accept only from the ALB SG on that service's port | Lwam | SG rules in `terraform plan` |
| T2.2 | Information disclosure | Task or DB reachable from the internet | No public IP on any ECS task or RDS instance; data subnets have **no route** to NAT or IGW at all | Lwam | route tables in plan |
| T2.3 | Tampering | Compromised container writes to its own filesystem to persist | Configure containers as **non-root** with a **read-only root filesystem**; writable paths limited to explicit temporary mounts | Wairimu | task definition JSON + container test |
| T2.4 | Information disclosure | **Outbound exfiltration** — a compromised task or malicious dependency uses the shared NAT egress path to send tenant data, MSISDNs, or Daraja credentials to an attacker-controlled host. [ADR-010](adr/ADR-010-networking-topology.md) is explicit about inbound security groups and silent about egress, so today's design permits arbitrary outbound HTTPS from the app subnets | Restrict egress rather than defaulting to allow-all: per-service SG egress rules scoped to the destinations that service actually needs; VPC endpoints for S3, ECR, Secrets Manager, and CloudWatch so AWS-service traffic never traverses NAT at all; the remaining internet-bound need is Daraja only, so route it through an egress control (allow-listed destinations) instead of open 0.0.0.0/0. VPC Flow Logs on the app subnets make unexpected destinations visible after the fact | Lwam | SG egress rules + VPC endpoint list in `terraform plan`; flow-log sample |
| T2.5 | Elevation | **SSRF** — a URL supplied in a sale, tenant configuration, or callback payload causes a service to fetch an attacker-chosen address, including the ECS task metadata endpoint (`169.254.170.2`), which would hand over the task role's temporary credentials | No service takes a caller-supplied URL as a fetch target; the Daraja base URL comes from configuration only, never from request data. Where a fetch target must ever become configurable, it is validated against an allow-list and link-local/private ranges are denied. The T2.4 egress restriction is the backstop that limits what a successful SSRF can reach | Hunter / Joyce | SSRF test cases against sale + tenant-config inputs |

### TB3 — Service ↔ service

| # | STRIDE | Threat | Mitigation | Owner | Proof |
|---|---|---|---|---|---|
| T3.1 | Elevation | `commission` calls Daraja B2C directly, bypassing the payments service's idempotency and ledger invariants | Architectural rule: **only `payments` holds Daraja credentials**. The `devops-g3/daraja` secret's resource policy and the task-role IAM policies grant `secretsmanager:GetSecretValue` on it to the `payments` task role only, so `commission` should be denied even if code is added by mistake | Lwam / Hunter | IAM policy in plan + denied secret-read test |
| T3.2 | Spoofing | Unauthorized internal caller invokes `payments`' B2C endpoint | Internal calls carry a service identity; the B2C route is not exposed through API Gateway at all (internal ALB path only) + SG-level restriction to the calling service's SG | Hunter | route map + SG rules |
| T3.3 | Repudiation | No way to attribute who triggered a payout | Every money-path span carries `tenant_id` + `idempotency_key` at 100% sampling; structured JSON logs carry `trace_id`/`span_id` ([ADR-008](adr/ADR-008-telemetry-conventions.md)) | Minage | trace capture in `evidence/` |
| T3.4 | Tampering | Duplicate or poisoned SQS message repeats work or blocks the commission worker | Idempotent consumers, schema validation, bounded retries, visibility-timeout tuning, and a DLQ with an alarm and replay procedure | Hunter / Minage | duplicate-message test + DLQ drill |

### TB4 — Service → data plane

| # | STRIDE | Threat | Mitigation | Owner | Proof |
|---|---|---|---|---|---|
| T4.1 | Information disclosure | **Cross-tenant data leak** via a missing `WHERE tenant_id = ?` | Postgres **RLS** on every tenant-owned table, `SET LOCAL app.current_tenant_id` per transaction, `BYPASSRLS` revoked on every service role including the owner ([ADR-005](adr/ADR-005-multi-tenancy-isolation.md)) | Joyce | RLS cross-tenant isolation test suite |
| T4.2 | Elevation | One service reads or writes another service's schema | Schema-per-service with least-privilege roles; cross-service reads only through explicit read-only views, never raw table grants ([ADR-002](adr/ADR-002-database.md)) | Lwam | `\dp` grant dump + plan |
| T4.3 | Tampering | Injection through sale line items or callback payload | Parameterized queries only (no string-built SQL); schema validation at the API boundary before anything reaches the DB layer | Joyce / Hunter | integration + malformed-input contract tests |
| T4.4 | Information disclosure | Data readable at rest by anyone with storage access | SSE-KMS on all five S3 buckets (shared CMK, rotation on, BPA at bucket **and** account level), RDS storage encryption, Redis encryption in transit + at rest ([ADR-003](adr/ADR-003-object-storage.md)) | Lwam | bucket policies + RDS config |
| T4.5 | Information disclosure | Cache poisoning / cross-tenant cache read in Redis | Every cache key is prefixed with `tenant_id`; no unkeyed global caches on tenant-scoped data | Joyce | key-naming convention + test |
| T4.6 | Denial of service | One tenant's or one service's runaway query starves the shared RDS instance | RDS Proxy per-credential connection limits; single-instance blast radius is a **known accepted risk** (AR-2 below) | Lwam | proxy config; [ADR-002](adr/ADR-002-database.md) consequences |
| T4.7 | Tampering | An attacker deletes or encrypts live data and unusable backups are discovered during recovery | Versioned/encrypted backups, restricted delete permissions, retention controls, and a restore drill into an isolated target before recovery is declared complete | Lwam / Minage | restore evidence with measured RPO/RTO |

### TB5 — Daraja callback

| # | STRIDE | Threat | Mitigation | Owner | Proof |
|---|---|---|---|---|---|
| T5.1 | Spoofing | **Forged callback** marks an unpaid sale as paid and later creates an invalid commission | Treat the callback as a notification, not proof of payment. Match it to a stored request, validate identifiers and amount, allow only legal state transitions, and query Daraja before final settlement whenever authenticity or state is uncertain. A secret callback path may reduce noise but is not sufficient authentication by itself ([ADR-007](adr/ADR-007-m-pesa-adapter.md)) | Hunter | forged-callback rejection test + verification trace |
| T5.2 | Tampering | Replayed or reordered callback produces a second ledger effect | Upsert on the unique `(MerchantRequestID, CheckoutRequestID)` pair; duplicate is a no-op on conflict; the state machine permits exactly one legal transition ([ADR-004](adr/ADR-004-idempotency-and-money-integrity.md)) | Hunter | replay/reorder invariant tests — also a G4 drill |
| T5.3 | Tampering | Amount in the callback differs from the amount of the sale it claims to settle | Amount is compared against the stored sale total (integer minor units, converted through the single shared whole-shilling function) before settlement; mismatch → do not settle, flag for reconciliation | Hunter | conversion + mismatch unit tests |
| T5.4 | Denial of service | Callback endpoint flooded, or Daraja goes silent entirely | Endpoint is throttled and rate-limited independently of the main API; a **timeout is never a decline** — the sale stays `pending` and the reconciliation worker resolves it from Daraja's authoritative status query, with SQS + DLQ making stuck work visible rather than silently dropped | Hunter / Minage | DLQ-depth alarm + forced-timeout drill |
| T5.5 | Repudiation | "We were double-charged" with no way to prove otherwise | 100% trace sampling on the money path; the full `pending → pending_reconciliation → resolved` path is reconstructible from a single `trace_id` | Minage | captured trace |
| T5.6 | Elevation | Callback path used to reach non-callback functionality | The callback route is narrowly scoped: it accepts one payload shape, performs no tenant-role resolution from the body, and cannot create tenants, sales, or payouts — only transition an existing payment | Hunter | route contract test |

### Money-state integrity (cross-cutting — an invariant boundary, not a network one)

The controls in [ADR-004](adr/ADR-004-idempotency-and-money-integrity.md) are what stop a double
charge or a double payout. This section does not restate that design; it asks **how those controls
themselves fail** — under an attacker, under a bug, or under an operator doing something reasonable
during an incident. Most of the entries below are the second case, which is also the likeliest.

| # | STRIDE | Threat | Mitigation | Owner | Proof |
|---|---|---|---|---|---|
| M1 | Information disclosure / Elevation | **Idempotency records are not tenant-scoped.** ADR-004 puts the unique constraint on `(service, key)`. A replayed key returns the **stored response verbatim**, so any key value that appears under two tenants — through collision, a leaked key in a log or shared client library, or a deliberate replay by tenant B of a key observed from tenant A — returns tenant A's payment response to tenant B. This is a tenant-isolation bypass that routes *around* the RLS backstop in [ADR-005](adr/ADR-005-multi-tenancy-isolation.md), because the idempotency table is consulted before the tenant-scoped query ever runs | Make the constraint `(service, tenant_id, key)` and store `tenant_id` on the record; on lookup, require the request's tenant to match the stored one, and treat a mismatch as a rejected request rather than a cache hit. Bring the table under RLS like every other tenant-owned table. **Requires an ADR-004 amendment — Hunter's call** | Hunter / Joyce | cross-tenant idempotency replay test asserting no response leak |
| M2 | Tampering | **Key expiry outlives the retry window it protects.** ADR-004 garbage-collects keys at 48h, but a DLQ replay or a client retry after a long incident can legitimately arrive later than that. The key is gone, the guard is silently absent, and the request executes a second time — a double payout, arriving specifically during the incident recovery when nobody is looking for it | Retention must exceed the longest legitimate retry path, including manual DLQ replay: raise it to ≥14d for money-path keys, or make the guard independent of key retention by keying B2C payouts deterministically on `(tenant_id, payout_period, attendant_id)` the way the daily commission run already does. A replay tool must refuse to run against a period whose keys have been collected | Hunter | replay-after-expiry test; DLQ replay drill at G4 |
| M3 | Tampering | **Cache used as a source of truth for a money decision.** Redis is cache-aside ([ADR-002](adr/ADR-002-database.md)). If the commission worker reads "sale is paid" from a stale or poisoned cache entry, it pays commission on money that was never confirmed received — and the payout is real even though the input was not | Money decisions read from Postgres only, never from cache. Cache is for read-only display paths (sale lists, dashboards); the commission calculation and any settlement check bypass it entirely. Enforced as a code-review rule on the `commission` and `payments` data layers, not just an intention | Joyce / Hunter | test asserting the commission calculation issues no cache read |
| M4 | Denial of service | **Retry amplification.** Client retries, SQS redelivery, and reconciliation polling compound: a brief Daraja slowdown becomes a self-inflicted request storm that exhausts connections, burns the Payments error budget, and slows the recovery it was meant to help | Bounded retries with exponential backoff **and jitter** at every layer; a circuit breaker on the Daraja client that fails fast once the provider is clearly down rather than queueing more work against it; reconciliation polling on a fixed schedule rather than per-request. Retry budgets are visible as a metric so a storm is diagnosable | Hunter / Minage | forced-outage drill showing bounded request rate + circuit-breaker metric |
| M5 | Tampering | **No detection invariant on the ledger.** ADR-004's unique constraints and state machine *prevent* known bad transitions, but nothing *detects* the unknown ones. A logic bug that writes a payout with no matching confirmed sale, or a half-applied transaction, can leave the ledger wrong without an immediate failure signal | Append-only, double-entry payout ledger: every entry balances, corrections are new reversing entries rather than updates or deletes. A scheduled reconciliation job asserts the invariants — sum of ledger entries per tenant per period nets to zero, every payout maps to exactly one confirmed paid sale, no confirmed paid sale is paid twice — and emits `commission_reconciliation_variance_total` ([ADR-008](adr/ADR-008-telemetry-conventions.md)). **Any non-zero variance pages**, since [`slo-error-budgets.md`](slo-error-budgets.md) already makes duplicate disbursement a zero-tolerance sub-SLO. **Double-entry is not in ADR-004 today — needs Hunter's decision** | Hunter / Minage | invariant job output + a seeded-imbalance test proving the alarm fires |
| M6 | Tampering / Elevation | **Refund or reversal bypasses the original payment.** A refund request could target another tenant's payment, refund more than the captured amount, or be replayed until the system creates multiple reversals | Refunds/reversals must reference an existing settled payment in the same tenant, enforce a remaining refundable balance, require their own idempotency key, and write reversing ledger entries instead of editing the original payment row. A successful retry returns the first refund result and creates no second money movement | Hunter / Joyce | refund replay, over-refund, and wrong-tenant tests |
| M7 | Tampering / Repudiation | **DB state and retry queue fall out of sync.** The service could commit `pending_reconciliation` without putting work on SQS, or enqueue the same retry work twice after a crash | Use a transactional outbox in the payments database: write the payment state change and the retry work item in the same DB transaction, then have a worker publish pending outbox rows to SQS. SQS consumers stay idempotent using the payment attempt/refund attempt ID, so duplicate queue delivery does not create a second ledger effect | Hunter / Minage | crash-after-commit test + duplicate-SQS-message test |
| M8 | Tampering | **Commission is paid before the payment is truly final.** A sale can look paid, commission gets disbursed, then the payment is later reversed, refunded, or corrected during reconciliation | Commission eligibility must require a settled and reconciled payment state, not just a callback-success event. If a later refund/reversal happens after commission has been paid, write a clawback or adjustment ledger entry instead of silently leaving the tenant short | Hunter / Minage | reversal-after-commission test + commission adjustment ledger evidence |
| M9 | Tampering / Elevation | **Commission rate tampering, and rates that are not effective-dated.** The asset table already calls a rate change "financial loss, quietly," but nothing controls it. Two failures: an attacker or careless owner raises the rate shortly before daily close and increases payouts; and, with no malice at all, if the close reads the rate *current at payout time* rather than the rate in force *at sale time*, one legitimate mid-day change silently re-prices the entire day's sales | Commission rates are **effective-dated and append-only** — a change writes a new row with a validity window, never an `UPDATE`. Every payout calculation resolves the rate as of the **sale's** timestamp, so the result is deterministic and reproducible months later. Rate changes are restricted to the tenant-owner role, written to an audit table with actor and timestamp, and a change above a configurable delta raises a Slack alert. Rate changes within N hours of the scheduled close are a reviewable event, not a silent one | Joyce / Hunter | rate-change audit trail + a test proving a mid-day rate change does not alter already-recorded sales |
| M10 | Spoofing / Tampering | **Payee substitution.** An attendant's MSISDN is changed shortly before the daily close, so the B2C payout lands on an attacker-controlled phone. This is a direct route from a compromised owner session to misdirected money: T1.4 stops an attendant reaching owner-only routes, but an owner-role compromise could still change payout details | Payout uses the attendant MSISDN **of record at the start of the payout period**, not the value at disbursement time. An MSISDN change starts a cooling-off window before it becomes payout-eligible, is written to the audit table with actor and timestamp, and notifies both the previous number and the tenant owner. Bulk MSISDN changes across several attendants alert immediately | Joyce / Hunter | payee-change-before-close test + audit trail |
| M11 | Tampering | **Partial batch failure in the daily close.** The worker pays 6 of 10 attendants and then crashes, hits a rate limit, or exhausts the float. On resume it must pay exactly the remaining 4 — not re-pay the 6, and not silently abandon the 4. "Duplicate disbursement = 0" ([`slo-error-budgets.md`](slo-error-budgets.md)) makes the first error high impact | The close is **per-attendant atomic, not per-batch**: each payout is its own ledger entry plus its own deterministic idempotency key `(tenant_id, payout_period, attendant_id)`, so resume is a natural re-run rather than special-case recovery logic. The run records a per-attendant terminal state; a run that ends with any attendant non-terminal is itself an alertable condition rather than a silent partial success | Hunter / Minage | kill-mid-batch drill showing correct resume, zero double-pays, and no dropped attendant |
| M12 | Tampering / Repudiation | **Internal consistency is not correctness.** M5's invariants prove our ledger agrees with *itself*. A systematic bug — a misparsed callback field, a wrong `ResultCode` mapping — produces a self-consistent ledger that disagrees with what Safaricom actually did. Only the provider's own records can settle that | Scheduled **external reconciliation** against Daraja: for every payment and payout in the period, compare our recorded state and amount against Daraja's transaction-status query (or statement, where available). Variances are classified — ours-only, theirs-only, amount mismatch — written to a reconciliation report, and any unexplained variance pages instead of becoming an unreviewed metric. Reconciliation order is documented in [`runbook.md`](runbook.md) so recovery can't declare success before it runs | Hunter / Minage | reconciliation report with a seeded deliberate variance, proving detection |
| M13 | Tampering | **Amount validation at the input edge.** T5.3 checks the callback amount against the sale, and [ADR-004](adr/ADR-004-idempotency-and-money-integrity.md) fixes the minor-units/whole-shilling boundary, but nothing validates the sale total as it is *created*: a negative quantity, a discount that drives a line or total below zero, an integer overflow on a large quantity × price, or per-line rounding that accumulates so line items don't sum to the recorded total. Negative amounts are the classic route to a negative-commission or reverse-payout bug | Validate at the API boundary before persistence: quantities and unit prices are positive integers within declared bounds, the computed total is re-derived server-side and never trusted from the client, discounts cannot drive a total below zero, totals are range-checked against an overflow-safe maximum, and a stored invariant asserts `sum(line_items) == sale_total`. Commission is never computed on a negative base | Joyce | boundary-value tests: negative, zero, overflow, and rounding-accumulation cases |
| M14 | Tampering | **Period boundary and clock.** The close runs at **06:30 EAT** while infrastructure runs in UTC. A sale at 23:59 EAT can land in the wrong payout period; a re-run after the boundary can compute a different period than the original; and the deterministic key `(tenant_id, payout_period)` is only safe if `payout_period` means the same thing on every host and every re-run | `payout_period` is an explicit stored date in a declared tenant timezone, resolved once at the start of the run and carried through — never re-derived from `now()` inside the calculation, which is what makes a re-run diverge. Sale-to-period assignment uses the sale's stored timestamp against that same declared window. Hosts use a single time source; the boundary case (a sale in the last minute before close) is an explicit test, not an assumption | Hunter / Joyce | boundary-time test at 23:59/00:00 EAT + a re-run producing an identical period key |
| M15 | Denial of service | **Float exhaustion.** B2C draws from a funded working account. If it runs dry mid-close, payouts fail for reasons that have nothing to do with our code, and the failure looks like a bug — which is how a real incident gets misdiagnosed under time pressure. It also interacts badly with M4: a retry storm against an empty float | Check the available balance before starting the close and alert if it cannot cover the projected total; alert on a low-float threshold well ahead of the scheduled run; classify a float-exhaustion failure distinctly from a technical failure so the runbook's first action is "fund the account," not "debug the worker." Attendants left unpaid stay in a resumable non-terminal state (M11) rather than being marked failed | Hunter / Minage | low-float alert + a forced-exhaustion drill showing correct classification and clean resume |

### TB6 — Developer / CI → AWS

| # | STRIDE | Threat | Mitigation | Owner | Proof |
|---|---|---|---|---|---|
| T6.1 | Spoofing | Leaked long-lived AWS access keys used to deploy | **No static AWS keys anywhere.** GitHub Actions assumes `devops-g3-ci-deploy` via **OIDC**, with the trust policy's `sub` condition scoped to this repository and the `main` ref — a fork or another repo cannot assume it | Wairimu | trust policy JSON + successful OIDC run |
| T6.2 | Elevation | CI role is effectively admin | Scope the CI deploy role to the required ECR, ECS, artifact, and Terraform operations; avoid unrestricted administrative permissions. Run PR plans without apply permissions and allow apply only from `main` through a protected environment ([ADR-009](adr/ADR-009-ci-cd-promotion-and-rollback.md)) | Wairimu / Lwam | IAM policy + protected-environment config |
| T6.3 | Information disclosure | A secret is committed, or printed into build logs / Terraform state | Secret scanning as a required PR check; secrets referenced by **ARN** in Terraform and injected by ECS at task start (`secrets` block), never passed as Terraform variables or plaintext env values; `.gitignore` covers `*.tfvars`, `*.tfstate`; state bucket is SSE-KMS + versioned + BPA | Wairimu / Lwam | scan job output + task definition showing ARN references only |
| T6.4 | Tampering | Unreviewed code reaches `main` and deploys | Branch protection: PR required, **CODEOWNERS review required**, `validate` + scan set as required status checks. Every path has exactly one DRI in `CODEOWNERS` | Wairimu | branch-protection settings + CODEOWNERS |
| T6.5 | Repudiation | Console click-ops changes infrastructure with no record | Everything is Terraform-managed; console changes earn no evidence credit and show up as plan drift. Drift is checked before each gate | Lwam | clean `terraform plan` at gate time |
| T6.6 | Repudiation | No account-level audit trail of who called which AWS API — a deleted resource, a read of `devops-g3/daraja`, or a manual ECS change cannot be attributed after the fact. Terraform drift detection shows *that* something changed, never *who* changed it | Enable a multi-region CloudTrail trail delivering to `devops-g3-logs-<account_id>` (SSE-KMS, versioned, BPA, log-file validation on), with the delivery path write-only for the trail and delete permissions withheld from every day-to-day role. Terraform-managed, like everything else | Lwam | trail configuration in `terraform plan` + a sample event showing a `GetSecretValue` call attributed to a principal |
| T6.7 | Spoofing / Tampering | **Adapter and environment confusion.** [ADR-007](adr/ADR-007-m-pesa-adapter.md) selects the M-Pesa adapter from configuration (`MPESA_ADAPTER=sandbox\|fake`). A misapplied environment variable could run `FakeMpesaAdapter` in a deployed environment, causing sales to settle without provider-confirmed money movement. The reverse error, a deployed environment pointed at another environment's credentials or callback URL, cross-contaminates payment state between environments. The release-blocker list already forbids this; it needs a control, not just a prohibition | The adapter is resolved at startup and **fails closed**: any deployed environment refuses to boot if the adapter is not `sandbox`, rather than defaulting. The resolved adapter, environment name, commit SHA, and image digest are exposed at `/healthz` and asserted by the post-deploy smoke check ([ADR-009](adr/ADR-009-ci-cd-promotion-and-rollback.md)), so a wrong adapter fails the deploy gate instead of quietly serving traffic. Callback URLs and credentials are environment-scoped secrets, never shared across environments | Wairimu / Hunter | `/healthz` output showing the resolved adapter + a smoke check that fails on a deliberately wrong adapter |

### TB7 — Supply chain (base images + dependencies → ECR → ECS)

| # | STRIDE | Threat | Mitigation | Owner | Proof |
|---|---|---|---|---|---|
| T7.1 | Tampering | Malicious or vulnerable transitive dependency ships to production | Dependency scanning + **SBOM generation** per build; pipeline **fails on fixable HIGH/CRITICAL**; unfixable findings are logged as accepted risk with an owner and expiry in [`scar-log.md`](scar-log.md), never silently passed ([ADR-009](adr/ADR-009-ci-cd-promotion-and-rollback.md)) | Wairimu | SBOM + scan report in `evidence/delivery/` |
| T7.2 | Tampering | Base image swapped underneath us between builds | Base images **pinned by digest**, not by floating tag; multi-stage build so build tooling never ships in the runtime layer | Wairimu | Dockerfile + build log |
| T7.3 | Spoofing | Ambiguity about which artifact is actually running | No `latest` tag ever; build by commit SHA, deploy the **immutable digest**, expose commit + digest at runtime (`/healthz`) and in pipeline evidence | Wairimu | runtime `/healthz` output vs pipeline log |
| T7.4 | Tampering | IaC misconfiguration introduces a public bucket or open SG | IaC scanning as a required PR check, in addition to human CODEOWNERS review | Wairimu | scan job output |
| T7.5 | Elevation | An old vulnerable image is redeployed during a rollback | ECR enhanced scanning on push; ECR lifecycle policy keeps a **minimum retention count** so rollback targets exist, and rollback targets are known-good SHAs, not arbitrary old ones | Wairimu | ECR scan findings + lifecycle policy |
| T7.6 | Tampering | A build or deployment consumes a replaced pipeline artifact | Separate artifact bucket permissions by role, enable versioning and KMS encryption, record checksums/digests, and promote the same immutable image digest that passed the gates | Wairimu | artifact metadata + deployed digest comparison |

### TB8 — Telemetry and operations

| # | STRIDE | Threat | Mitigation | Owner | Proof |
|---|---|---|---|---|---|
| T8.1 | Information disclosure | Raw MSISDNs, callback secret paths, or Daraja tokens end up in logs, spans, metric labels, k6 output, or a screenshot in `evidence/` | Central redaction in the `services/_shared` telemetry wrapper (see PII rule above); no secret or MSISDN is ever a metric **label** (labels are high-cardinality-visible and land in AMP); evidence artifacts are reviewed for PII before commit | Minage / Lwam | redaction unit tests + a log/trace sample in `evidence/` |
| T8.2 | Spoofing | Slack webhook leaks; attacker posts fake "recovered" alerts and hides a real incident | `SLACK_WEBHOOK_URL` lives in Secrets Manager only — never in Git, Terraform state, or build logs; rotated if ever exposed. Alerts carry a Grafana panel link so a claim can be checked against the actual signal, not believed on its own | Minage | secret ARN reference + firing/recovery evidence |
| T8.3 | Information disclosure | Self-hosted Grafana ([ADR-001](adr/ADR-001-aws-region.md)) is exposed publicly or retains a default administrator password | Place Grafana in private app subnets, disable anonymous access, keep administrator credentials in Secrets Manager, and restrict operator access | Lwam / Minage | task definition + SG rules + auth test |
| T8.4 | Repudiation | ALB access logs, the audit trail for edge traffic, are missing or mutable | Enable ALB access logging to `devops-g3-logs-<account_id>`; keep the bucket private, versioned, SSE-KMS encrypted, and retained according to [ADR-003](adr/ADR-003-object-storage.md) | Lwam | bucket policy + sample log objects |
| T8.5 | Denial of service / Repudiation | **Critical alert does not fire.** The service is failing, callback lag is growing, or the DLQ is filling, but the alert rule is missing, points at the wrong metric, or routes to the wrong Slack channel | Alerts are defined as code, reviewed with the service they protect, and tested with a deliberate failure. Each critical alert includes the owner, service, user impact, first safe action, and dashboard/runbook link. Required alerts include POS 5xx/error-budget burn, payments callback lag, DLQ depth, reconciliation variance, duplicate disbursement, low float, and adapter mismatch | Minage / service owner | alert-rule export + red/green evidence showing the alert fires and clears |
| T8.6 | Denial of service | **Alert noise hides the real incident.** Low-value alerts page too often, so operators ignore or miss the payment/commission alert that matters | Page only on symptoms tied to user impact or money safety; route warning-level alerts to tickets/dashboards. Burn-rate alerts follow [`slo-error-budgets.md`](slo-error-budgets.md), and every page has a runbook entry with a recovery signal. Alerts that fire without action are removed, tuned, or downgraded | Minage | alert review notes + runbook entry for each paging alert |

## Accepted risks

Each has an owner and an expiry. On expiry it is either fixed or explicitly re-accepted in a PR —
"it's been like that for a while" is not a re-acceptance. Anything that actually bites us gets
logged in [`scar-log.md`](scar-log.md) as it happens.

| ID | Risk | Why accepted | Owner | Expiry / trigger |
|---|---|---|---|---|
| AR-1 | **Single NAT Gateway in `dev`** — one point of egress failure; loses Daraja reachability for the whole VPC ([ADR-010](adr/ADR-010-networking-topology.md)) | Cost, in a region already more expensive than `us-west-2` | Lwam | Upgrade to one-per-AZ **before any G4 drill that claims AZ-independent egress** |
| AR-2 | **Single-AZ, single-instance RDS in `dev`** — shared blast radius, and an AZ loss is an outage ([ADR-002](adr/ADR-002-database.md)) | Cost; capstone-scale load | Lwam | Multi-AZ standby **before G4** |
| AR-3 | **Daraja sandbox callbacks are unsigned** — caller identity cannot be cryptographically established, so settlement correctness rests on TillFlow-side verification (match to a stored request, amount and identifier checks, legal-transition-only state machine, and a Daraja status query before final settlement). The secret callback path reduces noise; it is not authentication (T5.1) | Safaricom's sandbox does not provide a callback signature we can verify in this capstone | Hunter | Permanent for this capstone. A production launch requires a replacement verification design — IP allow-listing of Safaricom's callback ranges, and mTLS if offered — and is listed as a release blocker above |
| AR-4 | **One shared KMS CMK across all five S3 buckets** — compromise of the key affects all five ([ADR-003](adr/ADR-003-object-storage.md)) | Per-bucket CMK overhead not justified at this scale | Lwam | Revisit if any bucket takes on genuinely different-sensitivity data |
| AR-5 | **10% trace sampling on `pos`/`web`** — a specific non-error request may have no trace during an investigation | Volume/cost; always-sample-on-error keeps real failures traceable ([ADR-008](adr/ADR-008-telemetry-conventions.md)) | Minage | Revisit if an incident is materially delayed by a missing trace |
| AR-6 | **No WAF in front of API Gateway** | Cost and setup time against a sandbox-only workload with no real customer data | Lwam | Re-evaluate at G3 if the k6 spike test or logs show abusive traffic patterns |

## Explicitly out of scope

- **Malicious activity by an authorized cloud administrator** — partially reduced through CODEOWNERS
  review (T6.4), least privilege (T6.2), the CloudTrail audit trail (T6.6), and Terraform drift
  detection (T6.5). Those detect and attribute; they do not prevent. Full privileged-access
  management — break-glass accounts, session recording, dual authorization for destructive
  actions — is outside this capstone.
- **Compliance certification** (PCI-DSS, Kenya DPA registration) — a real deployment would need
  both; not assessed here.

## Required proof and evidence

Filed under `evidence/platform/` unless noted, with exact reproduction commands. The early items map
directly to the capstone requirements; the later money-safety items come from this threat model and
should be confirmed by the service owners before they become gate-blocking deliverables:

1. **Forged-callback rejection** — an unverified callback cannot settle a payment or write a paid
   ledger effect (`evidence/payments/`).
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
9. **Egress restriction** — `terraform plan` showing per-service SG egress rules and VPC endpoints
   for S3/ECR/Secrets Manager/CloudWatch, plus a VPC Flow Logs sample (T2.4).
10. **Supply chain** — SBOM + dependency/IaC/ECR scan reports with the HIGH/CRITICAL gate enforced
    (`evidence/delivery/`).
11. **Audit trail** — CloudTrail trail configuration plus a sample event attributing a
    `secretsmanager:GetSecretValue` call on `devops-g3/daraja` to a specific principal (T6.6).
12. **Backup restore** — a restore into an isolated target with measured RPO/RTO, performed before
    recovery is declared complete (T4.7, `evidence/reliability/`).
13. **Tenant-scoped idempotency** — a replay of tenant A's idempotency key by tenant B is rejected
    and leaks no stored response (M1, `evidence/payments/`).
14. **Ledger invariants** — reconciliation job output showing per-tenant/per-period balance, plus a
    seeded-imbalance test proving the variance alarm fires (M5, `evidence/payments/`).
15. **Refund safety** — replay, over-refund, and wrong-tenant refund attempts are rejected or return
    the original idempotent result without creating a second ledger effect (M6, `evidence/payments/`).
16. **Retry queue safety** — crash-after-commit and duplicate-SQS-message tests prove that
    reconciliation/retry work is eventually queued and still creates at most one ledger effect
    (M7, `evidence/payments/`).
17. **Commission payout safety** — a reversed or refunded payment cannot leave an already-paid
    commission uncorrected; the test shows a clawback/adjustment ledger entry (M8,
    `evidence/payments/`).
18. **Rate immutability** — the rate-change audit trail, plus a test proving a mid-day rate change
    does not re-price sales already recorded (M9, `evidence/product/`).
19. **Payee-change safety** — an MSISDN changed inside the cooling-off window is not used for that
    period's payout, and the change is attributable (M10, `evidence/product/`).
20. **Batch resume** — a kill-mid-batch drill on the daily close showing correct resume, zero double
    payments, and no attendant silently dropped (M11, `evidence/payments/`).
21. **External reconciliation** — a reconciliation report against Daraja with a deliberately seeded
    variance, proving detection rather than a clean number nobody checked (M12, `evidence/payments/`).
22. **Amount boundaries** — negative, zero, overflow, and rounding-accumulation cases rejected at the
    API boundary, with `sum(line_items) == sale_total` asserted (M13, `evidence/product/`).
23. **Period determinism** — a 23:59/00:00 EAT boundary test plus a re-run producing an identical
    `payout_period` key (M14, `evidence/payments/`).
24. **Float exhaustion** — low-float alert and a forced-exhaustion drill showing the failure is
    classified as funding, not as a code fault, and resumes cleanly (M15, `evidence/reliability/`).
25. **Adapter fail-closed** — `/healthz` exposing the resolved adapter, environment, commit SHA, and
    image digest, plus a post-deploy smoke check that fails on a deliberately wrong adapter
    (T6.7, `evidence/delivery/`).
26. **Alert firing evidence** — deliberate failure evidence showing critical alerts fire, reach the
    expected channel, link to a runbook/dashboard, and clear after recovery (T8.5,
    `evidence/reliability/`).
27. **Alert quality review** — each paging alert has a named owner, user impact, first safe action,
    and recovery signal; noisy non-actionable alerts are downgraded or removed (T8.6,
    `evidence/reliability/`).
