# SLIs / SLOs / Error budgets — DRI: Minage

> Starter targets from the brief. For each SLI define: numerator, denominator, window, target,
> exclusions, and the **user outcome** it represents.

| Service | Primary SLI (starter target) | 28-day error budget |
|---|---|---|
| Web | Eligible page/API-shell loads succeed ≥ 99.9%; p95 < 500 ms | 0.1% / 40m 19s |
| POS API | Valid sale writes accepted **exactly once** ≥ 99.9%; p95 < 400 ms | 0.1% / 40m 19s |
| Payments API | Valid STK/B2C accepted & callbacks processed within 60s ≥ 99.5% | 0.5% / 3h 21m 36s |
| Commission | Eligible payouts terminal by 06:30 EAT ≥ 99.0%; **duplicate disbursement = 0** | 1% events / 0.28 late runs |

Budget = eligible events × (1 − target). Invalid requests / genuine business declines may be excluded;
dependency outages still count when the user journey fails.


## Per-SLI definitions

| Service | SLI | Numerator | Denominator | Window | Target | Exclusions | User outcome |
|---|---|---|---|---|---|---|---|
| Web | Edge availability | Successful `/health`, `/ready`, and eligible web/API shell responses | All valid edge requests, excluding synthetic duplicate retries | 28 days; dashboard 5m/1h burn views | 99.9% | Invalid routes, auth failures caused by caller error | A tenant can reach TillFlow and start the sales journey |
| Web | Latency | Requests with p95 < 500ms | Eligible web/API shell requests | 5m rolling, reviewed over 28 days | p95 < 500ms | Health probes excluded from user SLI denominator | App shell loads fast enough for cashier use |
| POS | Idempotent sale writes | Valid sale writes accepted exactly once | All valid sale create attempts with idempotency key | 28 days | 99.9% | Malformed payloads, invalid tenant/auth | Cashier creates one sale and never duplicates money state |
| POS | Latency | Sale writes with p95 < 400ms | Valid sale write attempts | 5m rolling, reviewed over 28 days | p95 < 400ms | Caller/network retries not reaching API | Checkout is responsive at the counter |
| Payments | Payment acceptance + callback | STK/B2C accepted and callback processed within 60s | Valid payment attempts sent to provider | 28 days | 99.5% | Genuine provider/business declines; invalid MSISDN/test data | Customer gets a timely payment decision |
| Payments | Reconciliation safety | Attempts that settle through callback or reconciliation without DLQ growth | Attempts entering pending/reconciliation state | 28 days | 99.5% | Provider outage still counts if user journey is delayed | No payment is silently stuck |
| Commission | Daily close timeliness | Eligible payout runs terminal by 06:30 EAT | Scheduled payout runs | 28 days | 99.0% | Manually paused payout windows approved in incident notes | Merchants can trust daily commission settlement |
| Commission | Duplicate disbursement | Duplicate disbursement events = 0 | All payout ledger entries | Continuous | 0 tolerance | None | No merchant is paid twice for the same sale |

## Budget policy
- Fast-burn threshold: burn rate ≥ 14.4× sustained over both a 1h and 5m window (≈2% of the 28-day
  budget consumed in 1h) → page on-call + freeze non-essential releases to the affected service
  (enforced at the CI/CD promotion gate, [ADR-009](adr/ADR-009-ci-cd-promotion-and-rollback.md)).
- Slow-burn threshold: burn rate ≥ 3× sustained over both a 6h and 30m window (≈10% of budget in
  ~3 days) → ticket, alert only, no page.
- Commission's **duplicate disbursement = 0** sub-SLO is 0-tolerance and stands outside the
  percentage budget: any duplicate payout is an automatic incident + release freeze regardless of
  remaining budget.
- Resume feature work when: remaining 28-day budget is back above 20% **and** the triggering
  burn-rate alert has been clear for ≥1h.

See [ADR-006](adr/ADR-006-slos-and-error-budgets.md) for the reasoning behind these thresholds.
