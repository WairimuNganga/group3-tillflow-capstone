from commission.domain.state import commission_minor, payout_idempotency_key


def test_commission_minor_floor():
    assert commission_minor(10000, 200) == 200  # 2% of 100.00 KES minor
    assert commission_minor(1, 200) == 0
    assert commission_minor(99, 100) == 0
    assert commission_minor(100, 100) == 1


def test_payout_key_format():
    assert (
        payout_idempotency_key("t1", "2026-09-19", "att-7")
        == "t1:2026-09-19:att-7"
    )
