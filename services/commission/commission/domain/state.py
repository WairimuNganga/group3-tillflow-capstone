from __future__ import annotations

from enum import Enum


class InvalidStateTransitionError(ValueError):
    """Raised when a payout intent state change is not allowed."""


class CloseRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PayoutIntentState(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    COMPLETED = "completed"
    FAILED = "failed"


_INTENT_TRANSITIONS: dict[PayoutIntentState, frozenset[PayoutIntentState]] = {
    PayoutIntentState.PENDING: frozenset({PayoutIntentState.SUBMITTED, PayoutIntentState.FAILED}),
    PayoutIntentState.SUBMITTED: frozenset(
        {PayoutIntentState.COMPLETED, PayoutIntentState.FAILED}
    ),
    PayoutIntentState.COMPLETED: frozenset(),
    PayoutIntentState.FAILED: frozenset({PayoutIntentState.PENDING, PayoutIntentState.SUBMITTED}),
}


def assert_intent_transition(current: PayoutIntentState, target: PayoutIntentState) -> None:
    allowed = _INTENT_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidStateTransitionError(
            f"illegal payout intent transition: {current.value} -> {target.value}"
        )


def is_intent_terminal(state: PayoutIntentState) -> bool:
    return state in {PayoutIntentState.COMPLETED, PayoutIntentState.FAILED}


def payout_idempotency_key(tenant_id: str, payout_period: str, attendant_id: str) -> str:
    """Deterministic B2C key: tenant:period:attendant ([ADR-004] / M11)."""
    return f"{tenant_id}:{payout_period}:{attendant_id}"


def commission_minor(amount_minor_units: int, rate_bps: int) -> int:
    """floor(amount * rate_bps / 10000) — exact integer money math."""
    if amount_minor_units < 0 or rate_bps < 0:
        raise ValueError("amount and rate_bps must be non-negative")
    return (amount_minor_units * rate_bps) // 10000
