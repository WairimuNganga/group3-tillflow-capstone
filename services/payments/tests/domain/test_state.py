import pytest

from payments.domain.state import (
    InvalidStateTransitionError,
    PaymentState,
    PayoutState,
    assert_payment_transition,
    assert_payout_transition,
    is_payment_terminal,
    is_payout_terminal,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (PaymentState.PENDING, PaymentState.STK_SENT),
        (PaymentState.PENDING, PaymentState.PENDING_RECONCILIATION),
        (PaymentState.STK_SENT, PaymentState.PAID),
        (PaymentState.STK_SENT, PaymentState.FAILED),
        (PaymentState.STK_SENT, PaymentState.PENDING_RECONCILIATION),
        (PaymentState.PENDING_RECONCILIATION, PaymentState.PAID),
        (PaymentState.PENDING_RECONCILIATION, PaymentState.FAILED),
    ],
)
def test_legal_payment_transitions(current: PaymentState, target: PaymentState) -> None:
    assert_payment_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (PaymentState.PAID, PaymentState.PENDING),
        (PaymentState.PENDING, PaymentState.PAID),
        (PaymentState.STK_SENT, PaymentState.PENDING),
    ],
)
def test_illegal_payment_transitions(current: PaymentState, target: PaymentState) -> None:
    with pytest.raises(InvalidStateTransitionError):
        assert_payment_transition(current, target)


def test_failed_to_paid_allowed_for_late_success() -> None:
    assert_payment_transition(PaymentState.FAILED, PaymentState.PAID)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (PayoutState.PENDING, PayoutState.SUBMITTED),
        (PayoutState.SUBMITTED, PayoutState.COMPLETED),
        (PayoutState.SUBMITTED, PayoutState.FAILED),
    ],
)
def test_legal_payout_transitions(current: PayoutState, target: PayoutState) -> None:
    assert_payout_transition(current, target)


def test_terminal_payment_states() -> None:
    assert is_payment_terminal(PaymentState.PAID)
    assert is_payment_terminal(PaymentState.FAILED)
    assert not is_payment_terminal(PaymentState.STK_SENT)


def test_terminal_payout_states() -> None:
    assert is_payout_terminal(PayoutState.COMPLETED)
    assert is_payout_terminal(PayoutState.FAILED)
    assert not is_payout_terminal(PayoutState.SUBMITTED)
