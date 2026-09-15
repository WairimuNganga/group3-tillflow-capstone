from __future__ import annotations

from enum import Enum


class InvalidStateTransitionError(ValueError):
    """Raised when a payment or payout state change is not allowed."""


class PaymentState(str, Enum):
    """Payment lifecycle ([ADR-004])."""

    PENDING = "pending"
    STK_SENT = "stk_sent"
    PAID = "paid"
    FAILED = "failed"
    PENDING_RECONCILIATION = "pending_reconciliation"


class PayoutState(str, Enum):
    """B2C payout lifecycle."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    COMPLETED = "completed"
    FAILED = "failed"


_PAYMENT_TRANSITIONS: dict[PaymentState, frozenset[PaymentState]] = {
    PaymentState.PENDING: frozenset({PaymentState.STK_SENT, PaymentState.PENDING_RECONCILIATION}),
    PaymentState.STK_SENT: frozenset(
        {
            PaymentState.PAID,
            PaymentState.FAILED,
            PaymentState.PENDING_RECONCILIATION,
        }
    ),
    PaymentState.PENDING_RECONCILIATION: frozenset({PaymentState.PAID, PaymentState.FAILED}),
    PaymentState.PAID: frozenset(),
    # Late success after an out-of-order failure callback — success wins ([ADR-004]).
    PaymentState.FAILED: frozenset({PaymentState.PAID}),
}

_PAYOUT_TRANSITIONS: dict[PayoutState, frozenset[PayoutState]] = {
    PayoutState.PENDING: frozenset({PayoutState.SUBMITTED}),
    PayoutState.SUBMITTED: frozenset({PayoutState.COMPLETED, PayoutState.FAILED}),
    PayoutState.COMPLETED: frozenset(),
    PayoutState.FAILED: frozenset(),
}


def assert_payment_transition(current: PaymentState, target: PaymentState) -> None:
    allowed = _PAYMENT_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidStateTransitionError(
            f"illegal payment transition: {current.value} -> {target.value}"
        )


def assert_payout_transition(current: PayoutState, target: PayoutState) -> None:
    allowed = _PAYOUT_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidStateTransitionError(
            f"illegal payout transition: {current.value} -> {target.value}"
        )


def is_payment_terminal(state: PaymentState) -> bool:
    return state in {PaymentState.PAID, PaymentState.FAILED}


def is_payout_terminal(state: PayoutState) -> bool:
    return state in {PayoutState.COMPLETED, PayoutState.FAILED}
