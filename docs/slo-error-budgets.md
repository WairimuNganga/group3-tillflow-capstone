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
