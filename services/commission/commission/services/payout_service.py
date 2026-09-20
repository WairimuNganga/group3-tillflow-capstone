from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from tillflow_shared.otel import business_counter
from tillflow_shared.otel.middleware import traced

from commission.clients.payments import PaymentsClient, PaymentsClientError
from commission.domain.models import PayoutIntent
from commission.domain.state import (
    PayoutIntentState,
    assert_intent_transition,
    is_intent_terminal,
    payout_idempotency_key,
)

_log = logging.getLogger(__name__)

payouts_total = business_counter(
    "commission_payouts_total",
    "Attendant B2C payouts by outcome.",
)


class PayoutIntentRepository(Protocol):
    async def get(
        self, tenant_id: str, payout_period: date, attendant_id: str
    ) -> PayoutIntent | None: ...

    async def upsert(self, intent: PayoutIntent) -> PayoutIntent: ...


@dataclass(frozen=True, slots=True)
class SubmitResult:
    intent: PayoutIntent
    already_requested: bool
    next_payout_period: date


class PayoutService:
    """Submit one attendant payout via Payments B2C (never Daraja)."""

    def __init__(
        self,
        *,
        intents: PayoutIntentRepository,
        payments: PaymentsClient,
    ) -> None:
        self._intents = intents
        self._payments = payments

    async def submit(
        self, *, tenant_id: str, payout_period: date, attendant_id: str
    ) -> SubmitResult:
        with traced(
            "commission.attendant_payout",
            tenant_id=tenant_id,
            attendant_id=attendant_id,
            payout_period=str(payout_period),
        ):
            return await self._submit(tenant_id, payout_period, attendant_id)

    async def _submit(
        self, tenant_id: str, payout_period: date, attendant_id: str
    ) -> SubmitResult:
        next_period = payout_period + timedelta(days=1)
        intent = await self._intents.get(tenant_id, payout_period, attendant_id)
        if intent is None:
            raise ValueError(
                f"no payout intent for {tenant_id}/{payout_period}/{attendant_id}"
            )
        if is_intent_terminal(intent.intent_state) and intent.state == (
            PayoutIntentState.COMPLETED.value
        ):
            payouts_total.add(1, {"result": "already_completed"})
            return SubmitResult(
                intent=intent, already_requested=True, next_payout_period=next_period
            )
        if intent.state == PayoutIntentState.SUBMITTED.value and intent.payments_payout_id:
            payouts_total.add(1, {"result": "already_submitted"})
            return SubmitResult(
                intent=intent, already_requested=True, next_payout_period=next_period
            )

        key = payout_idempotency_key(tenant_id, payout_period.isoformat(), attendant_id)
        try:
            result = await self._payments.initiate_b2c(
                tenant_id=tenant_id,
                idempotency_key=key,
                attendant_id=attendant_id,
                phone_number=intent.phone_number,
                amount_minor_units=intent.amount_minor_units,
            )
        except PaymentsClientError as exc:
            if intent.state == PayoutIntentState.PENDING.value:
                assert_intent_transition(intent.intent_state, PayoutIntentState.FAILED)
            intent.state = PayoutIntentState.FAILED.value
            intent.failure_reason = str(exc)
            intent.updated_at = datetime.now(UTC)
            await self._intents.upsert(intent)
            payouts_total.add(1, {"result": "failed"})
            raise

        if intent.state == PayoutIntentState.PENDING.value or intent.state == (
            PayoutIntentState.FAILED.value
        ):
            assert_intent_transition(
                PayoutIntentState.PENDING
                if intent.state == PayoutIntentState.PENDING.value
                else PayoutIntentState.FAILED,
                PayoutIntentState.SUBMITTED,
            )
        intent.state = PayoutIntentState.SUBMITTED.value
        intent.payments_payout_id = result.payout_id
        intent.failure_reason = None
        intent.updated_at = datetime.now(UTC)
        # Treat Payments "submitted"/"completed" as progress; mark completed when
        # Payments already reports completed (fake immediate path).
        if result.state == "completed":
            assert_intent_transition(PayoutIntentState.SUBMITTED, PayoutIntentState.COMPLETED)
            intent.state = PayoutIntentState.COMPLETED.value
        saved = await self._intents.upsert(intent)
        payouts_total.add(1, {"result": saved.state})
        return SubmitResult(
            intent=saved, already_requested=False, next_payout_period=next_period
        )

    async def mark_completed(
        self, *, tenant_id: str, payout_period: date, attendant_id: str
    ) -> PayoutIntent:
        """Local/test helper when B2C result is observed outside the worker."""
        intent = await self._intents.get(tenant_id, payout_period, attendant_id)
        if intent is None:
            raise ValueError("intent not found")
        if intent.state == PayoutIntentState.COMPLETED.value:
            return intent
        assert_intent_transition(intent.intent_state, PayoutIntentState.COMPLETED)
        intent.state = PayoutIntentState.COMPLETED.value
        intent.updated_at = datetime.now(UTC)
        return await self._intents.upsert(intent)
