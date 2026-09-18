"""Sale state-machine unit tests (no DB)."""

import pytest

from pos.domain.state import (
    InvalidStateTransitionError,
    SaleStatus,
    assert_sale_transition,
    can_transition,
    is_sale_terminal,
)

LEGAL = [
    (SaleStatus.PENDING, SaleStatus.AWAITING_PAYMENT),
    (SaleStatus.PENDING, SaleStatus.CANCELLED),
    (SaleStatus.AWAITING_PAYMENT, SaleStatus.PAID),
    (SaleStatus.AWAITING_PAYMENT, SaleStatus.FAILED),
]

ILLEGAL = [
    (SaleStatus.PENDING, SaleStatus.PAID),           # can't skip payment
    (SaleStatus.PENDING, SaleStatus.FAILED),
    (SaleStatus.AWAITING_PAYMENT, SaleStatus.CANCELLED),
    (SaleStatus.PAID, SaleStatus.FAILED),            # terminal
    (SaleStatus.PAID, SaleStatus.AWAITING_PAYMENT),  # no going back
    (SaleStatus.FAILED, SaleStatus.PAID),
    (SaleStatus.CANCELLED, SaleStatus.PENDING),
]


@pytest.mark.parametrize("current,target", LEGAL)
def test_legal_transitions(current, target):
    assert can_transition(current, target)
    assert_sale_transition(current, target)  # does not raise


@pytest.mark.parametrize("current,target", ILLEGAL)
def test_illegal_transitions(current, target):
    assert not can_transition(current, target)
    with pytest.raises(InvalidStateTransitionError):
        assert_sale_transition(current, target)


def test_terminal_states():
    for term in (SaleStatus.PAID, SaleStatus.FAILED, SaleStatus.CANCELLED):
        assert is_sale_terminal(term)
        assert all(not can_transition(term, s) for s in SaleStatus)
    assert not is_sale_terminal(SaleStatus.PENDING)
    assert not is_sale_terminal(SaleStatus.AWAITING_PAYMENT)


def test_same_state_is_not_a_transition():
    # The service treats current==target as a no-op before calling this.
    with pytest.raises(InvalidStateTransitionError):
        assert_sale_transition(SaleStatus.PAID, SaleStatus.PAID)
