# Evidence — Product + POS
**DRI: Joyce** · cross-reviews Payments

Drop here, each with **exact reproduction commands** (screenshots alone earn no credit):
- [x] Commits / PR links for owned work — POS handoff [#28](https://github.com/WairimuNganga/group3-tillflow-capstone/pull/28); commission + web demo [#57](https://github.com/WairimuNganga/group3-tillflow-capstone/pull/57)
- [x] ADR(s) for this area — [ADR-004](../../docs/adr/ADR-004-idempotency-and-money-integrity.md), [ADR-005](../../docs/adr/ADR-005-multi-tenancy-isolation.md)
- [x] Tests — POS (`services/pos/tests/`), commission invariants
      (`services/commission/tests/invariants/`)
- [x] Runtime proof — [`e2e-flow-output.txt`](e2e-flow-output.txt); commission pack below
- [x] Reproduction commands — [`how-to-reproduce.md`](how-to-reproduce.md)
- [x] Commission worker — [`commission-close-b2c.md`](commission-close-b2c.md)

## Filed packs

| Pack | Notes |
|------|-------|
| [commission-close-b2c.md](commission-close-b2c.md) | Close → ledger → B2C invariants + reproduce commands |
| [web-demo-shell.md](web-demo-shell.md) | Jinja demo shell + [`web-screenshots/`](web-screenshots/) (home, sales, **commission day**, **payouts**) |
