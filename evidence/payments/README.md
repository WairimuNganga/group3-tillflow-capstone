# Evidence — Payments + integrity
**DRI: Hunter** · cross-reviews Product

Drop here, each with **exact reproduction commands** (screenshots alone earn no credit):
- [ ] Commits / PR links for owned work
- [x] ADR(s) for this area — [ADR-004](../../docs/adr/ADR-004-idempotency-and-money-integrity.md), [ADR-007](../../docs/adr/ADR-007-m-pesa-adapter.md)
- [x] Tests (unit / integration / invariant / contract as applicable) — see pack below (`43 passed`)
- [x] Runtime proof (fake curls + Daraja sandbox STK/callback via ngrok) — see pack below
- [x] Reproduction commands — included in the pack (setup + every curl)

## Filed packs

| Pack | Tester | Date | Notes |
|------|--------|------|-------|
| [mpesa-integration-manual-test.md](mpesa-integration-manual-test.md) | Minage | 2026-09-15/16 | Fake adapter manual HTTP + Daraja sandbox e2e; DRI sign-off pending |
| [commission-view-and-daraja-secret.md](commission-view-and-daraja-secret.md) | Hunter | 2026-09-16 | Confirmed commission RO view fields + `devops-g3/daraja` JSON keys |

View shipped: `payments.v_paid_sales_for_commission` (`alembic` `0004_paid_sales_commission_view`).

