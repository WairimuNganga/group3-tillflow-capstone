# Evidence — Product + POS
**DRI: Joyce** · cross-reviews Payments

Drop here, each with **exact reproduction commands** (screenshots alone earn no credit):
- [ ] Commits / PR links for owned work
- [ ] ADR(s) for this area
- [x] Tests — POS 46 (`services/pos/tests/`), the POS↔Payments contract in
      `test_payment_flow.py`; Payments' side in `services/payments/tests/api/test_pos_notification.py`
- [x] Runtime proof — [`e2e-flow-output.txt`](e2e-flow-output.txt): a recorded
      40-assertion run of the live two-service flow
- [x] Reproduction commands — [`how-to-reproduce.md`](how-to-reproduce.md)
- [ ] Commission worker (daily close → payout ledger → B2C) — not built yet
