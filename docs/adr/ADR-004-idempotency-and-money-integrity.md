# ADR-004: Idempotency & money integrity

- **Status:** Accepted
- **DRI:** Hunter
- **Date:** 2026-09-08

## Context
Sale creation, STK push, Daraja callbacks, and B2C payouts all move money or record that money
moved. Networks time out, Daraja can retry or reorder callbacks, and clients can retry requests.
None of that may ever result in a duplicate charge, a duplicate payout, or a lost sale. M-Pesa
itself only transacts in **whole shillings**; our own ledger math must not silently accrue
fractional-shilling drift at that boundary.

## Decision
- **Idempotency keys everywhere money moves**: sale creation, STK initiation, callback processing,
  and B2C payout each require a client- or system-generated key (UUIDv4) sent as an
  `Idempotency-Key` header (or, for the daily commission run, derived deterministically from
  `(tenant_id, payout_period)`). Each service schema has an `idempotency_keys` table — unique
  constraint on `(service, key)` — storing a digest of the original response. A replayed key returns
  the stored response verbatim; it never re-triggers the underlying STK/B2C call. Keys are retained
  48h then garbage-collected.
- **Timeout ≠ decline**: if Daraja doesn't answer synchronously, the sale/payment stays
  `pending` — it is never auto-marked `failed`. A reconciliation worker polls Daraja's transaction
  status query for any record stuck in `pending` past a threshold and resolves it from the
  authoritative source, not from client-side assumption. Retries of the reconciliation call and of
  B2C payouts are driven off an SQS queue with a dedicated DLQ, so a stuck reconciliation attempt is
  visible (DLQ depth) rather than silently dropped.
- **Callback dedup**: the payments callback handler upserts on Daraja's
  `(MerchantRequestID, CheckoutRequestID)` pair with a unique constraint; a duplicate or
  out-of-order callback is a no-op on conflict, not a second ledger write.
- **Minor units, whole-shilling boundary**: the ledger stores amounts as integer minor units
  (1 KES = 100 units) for internal precision. A single, unit-tested conversion function at the
  `services/_shared` boundary rounds to the nearest whole shilling before any call to Daraja and
  reconstructs minor units from Daraja's whole-shilling responses — this function is the only place
  in the codebase allowed to do that conversion.
- **State machine**: `pending → stk_sent → {callback_success | callback_failure | timeout}`, with
  `timeout → pending_reconciliation → resolved` handled exclusively by the reconciliation worker.

## Alternatives considered
- **Treat timeout as decline, let the client retry** — rejected: if the STK actually succeeded after
  the client gave up waiting, a naive retry double-charges the customer. This is exactly what the
  brief calls out as the failure mode to avoid.
- **Unique-constraint-only idempotency (no stored response)** — rejected: prevents duplicate rows but
  can't return the original response to an exact-replay client, which client retry logic depends on.
- **Floating-point KES amounts** — rejected: standard source of rounding/precision bugs in financial
  math; integer minor units is the accepted mitigation.

## Consequences
- Every money-moving endpoint needs the shared idempotency middleware in `services/_shared` — this
  is a hard dependency, not opt-in.
- The reconciliation worker and its SQS/DLQ retry path are now required operational surface with
  their own failure modes to monitor (feeds [ADR-006](ADR-006-slos-and-error-budgets.md)'s Payments
  and Commission SLIs).
- The minor-units ↔ whole-KES conversion function is exhaustively unit-tested as the required proof
  for this ADR — any change to it is a high-scrutiny PR.

## Required proof (from brief)
Invariant tests + trace: unit tests asserting no-double-pay under key replay, and a captured trace
showing the `pending → pending_reconciliation → resolved` path end to end.
