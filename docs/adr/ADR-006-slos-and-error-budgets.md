# ADR-006: SLOs & error budgets

- **Status:** Accepted
- **DRI:** Minage
- **Date:** 2026-09-08

## Context
Four services carry very different failure costs: a slow storefront page is an inconvenience, a
lost or duplicated payment is not. Each service needs a measurable budget tied to a concrete user
outcome, not a generic uptime number, and the team needs a shared, pre-agreed policy for what
happens when a budget burns down — otherwise "we're over budget" has no consequence and the SLO is
decorative.

## Decision
Per-service SLIs, targets, and 28-day error budgets are defined in
[`docs/slo-error-budgets.md`](../slo-error-budgets.md) — this ADR is the record of *why* those
targets and that policy were chosen; the doc itself is the required proof and the numbers live
there, not duplicated here (to avoid the two drifting apart).

Summary of the shape of each SLI (see the doc for exact numerator/denominator/window/target):
- **Web** — availability + latency of the page/API shell. User outcome: *the storefront/admin
  loads.*
- **POS API** — sale writes accepted exactly once, with a latency bound. User outcome: *a cashier
  can ring up a sale without the till hanging or double-recording it.*
- **Payments API** — STK/B2C accepted and callbacks processed within a bounded time. User outcome:
  *the customer's payment prompt appears promptly and its outcome is reflected quickly.*
- **Commission** — eligible payouts terminal by the daily cutoff (06:30 EAT, matching the
  EventBridge-scheduled daily close described in `docs/architecture.md`), with **duplicate
  disbursement held at zero** as a hard sub-SLO, not folded into the percentage target. User
  outcome: *sellers are paid correctly and on time.*

**Budget policy** (fills the TODOs in `docs/slo-error-budgets.md`):
- **Fast-burn**: burn rate ≥ 14.4× sustained over both a 1h and 5m window (≈2% of the 28-day budget
  in 1h) → page on-call immediately and freeze non-essential releases to the affected service
  (enforced at the promotion gate in [ADR-009](ADR-009-ci-cd-promotion-and-rollback.md)).
- **Slow-burn**: burn rate ≥ 3× sustained over both a 6h and 30m window (≈10% of budget in ~3 days)
  → ticket, no page.
- **Commission's duplicate-disbursement sub-SLO** is 0-tolerance: any duplicate payout is an
  automatic incident and release freeze regardless of the percentage budget's remaining balance —
  the percentage target alone would let a single duplicate payout hide inside "1% events" slack,
  which isn't acceptable for money actually leaving the business.
- **Resume feature work when**: remaining 28-day budget is back above 20% **and** the triggering
  burn-rate alert has been clear for ≥1h (avoids thrashing the freeze on a single noisy spike).

## Alternatives considered
- **One platform-wide uptime SLO** — rejected: hides which service is actually degraded, and
  money-path services need a tighter target than the storefront.
- **Latency-only SLOs** — rejected: a service can be fast and wrong (e.g., a fast but incorrect
  commission calc). Success-ratio SLIs with a latency threshold folded in, not a separate SLI, are
  used instead.
- **Uniform burn-rate policy for Commission** — rejected: Commission's daily-batch shape (one run a
  day, not a continuous request stream) doesn't fit a multiwindow burn-rate model well; it's treated
  as an event-based budget instead, with the duplicate-disbursement case carved out as absolute.

## Consequences
- Instrumentation for these SLIs must use consistent metric names/labels across services — this is
  the dependency on [ADR-008](ADR-008-telemetry-conventions.md).
- The release-freeze rule needs an actual enforcement point in CI/CD, not just a policy statement —
  tracked in [ADR-009](ADR-009-ci-cd-promotion-and-rollback.md).
- Treating Commission's duplicate-disbursement case as always-an-incident means the team commits to
  actually paging on it, not just logging it — this should be rehearsed once before it's needed for
  real.

## Required proof (from brief)
`docs/slo-error-budgets.md` (populated with the table above and the budget policy).
