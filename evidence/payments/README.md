# Evidence — Payments + integrity
**DRI: Hunter** · cross-reviews Product

Drop here, each with **exact reproduction commands** (screenshots alone earn no credit):
- [x] Commits / PR links for owned work — shared M-Pesa adapter [#4](https://github.com/WairimuNganga/group3-tillflow-capstone/pull/4); payments service [#22](https://github.com/WairimuNganga/group3-tillflow-capstone/pull/22); commission→Payments B2C integration (cross-cut) [#57](https://github.com/WairimuNganga/group3-tillflow-capstone/pull/57). Platform migrations touching `payments` schema: [#63](https://github.com/WairimuNganga/group3-tillflow-capstone/pull/63). G4 payout-queue IAM: [#68](https://github.com/WairimuNganga/group3-tillflow-capstone/pull/68).
- [x] ADR(s) for this area — [ADR-004](../../docs/adr/ADR-004-idempotency-and-money-integrity.md), [ADR-007](../../docs/adr/ADR-007-m-pesa-adapter.md)
- [x] Tests (unit / integration / invariant / contract as applicable) — `services/payments/tests/` (run with `DATABASE_URL=` and `MPESA_ADAPTER=fake`; see packs below)
- [x] Runtime proof (fake curls + Daraja sandbox STK/callback via ngrok) — see pack below
- [x] Reproduction commands — included in the pack (setup + every curl)

## G3 / G4 cross-links (Payments boundary)

| Topic | Artifact |
|-------|----------|
| B2C only via Payments (never Daraja from commission) | [commission-payout-via-payments-20260922.md](../reliability/phase-f/traces/commission-payout-via-payments-20260922.md) |
| Timed STK → callback → B2C invariants | [drill-1-2-timed-20260922.log](../reliability/drill-1-2-timed-20260922.log) |
| Deployed callback + X-Ray (edge) | [drill-2-deployed-callback-20260922.json](../reliability/drill-2-deployed-callback-20260922.json) |
| Review gap closure index | [all-gates-review-follow-up.md](../../docs/all-gates-review-follow-up.md) |

**Viva talking points:** idempotency keys and callback dedup (ADR-004); forged-callback rejection; STK timeout → reconcile; B2C idempotency on `(tenant, period, attendant)`; `payments.v_paid_sales_for_commission` as the only paid-sale read for commission.

## Filed packs

| Pack | Tester | Date | Notes |
|------|--------|------|-------|
| [mpesa-integration-manual-test.md](mpesa-integration-manual-test.md) | Minage | 2026-09-15/16 | Fake adapter manual HTTP + Daraja sandbox e2e; DRI sign-off pending |
| [commission-view-and-daraja-secret.md](commission-view-and-daraja-secret.md) | Hunter | 2026-09-16 | Confirmed commission RO view fields + `devops-g3/daraja` JSON keys |

View shipped: `payments.v_paid_sales_for_commission` (`alembic` `0004_paid_sales_commission_view`).
