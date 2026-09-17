from __future__ import annotations

from enum import StrEnum


class InvalidStateTransitionError(ValueError):
    """Raised when a sale state change is not allowed."""


class SaleStatus(StrEnum):
    """Sale lifecycle (ADR-004). POS owns sale state.

    A sale is created ``pending``; once STK is initiated it is
    ``awaiting_payment``; the payment outcome drives it to ``paid`` or
    ``failed``. A ``pending`` sale can be ``cancelled`` before payment.
    """

    PENDING = "pending"
    AWAITING_PAYMENT = "awaiting_payment"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TRANSITIONS: dict[SaleStatus, frozenset[SaleStatus]] = {
    SaleStatus.PENDING: frozenset({SaleStatus.AWAITING_PAYMENT, SaleStatus.CANCELLED}),
    SaleStatus.AWAITING_PAYMENT: frozenset({SaleStatus.PAID, SaleStatus.FAILED}),
    SaleStatus.PAID: frozenset(),
    SaleStatus.FAILED: frozenset(),
    SaleStatus.CANCELLED: frozenset(),
}


def can_transition(current: SaleStatus, target: SaleStatus) -> bool:
    return target in _TRANSITIONS.get(current, frozenset())


def assert_sale_transition(current: SaleStatus, target: SaleStatus) -> None:
    """Raise :class:`InvalidStateTransitionError` unless the move is allowed.

    Re-asserting the current state is rejected; callers wanting at-least-once
    safety (e.g. a replayed payments callback) should treat ``current == target``
    as a no-op before calling this.
    """
    if not can_transition(current, target):
        raise InvalidStateTransitionError(
            f"illegal sale transition: {current.value} -> {target.value}"
        )


def is_sale_terminal(state: SaleStatus) -> bool:
    return not _TRANSITIONS.get(state, frozenset())
