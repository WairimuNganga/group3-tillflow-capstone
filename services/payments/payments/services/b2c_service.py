from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from tillflow_shared.money import from_whole_kes, to_whole_kes
from tillflow_shared.mpesa.adapter import MpesaAdapter
from tillflow_shared.mpesa.exceptions import MpesaTimeoutError
from tillflow_shared.mpesa.types import B2CRequest
from tillflow_shared.otel import business_counter
from tillflow_shared.otel.middleware import traced

from payments.domain.models import PaymentLedgerEntry, Payout
from payments.domain.state import PayoutState, assert_payout_transition, is_payout_terminal
from payments.repositories.memory_settlement import InMemoryLedgerRepository
from payments.repositories.payout_memory import InMemoryPayoutRepository
from payments.repositories.payout_postgres import PostgresPayoutRepository
from payments.repositories.postgres_settlement import PostgresLedgerRepository

b2c_initiated = business_counter(
    "payments_b2c_initiated_total",
    "B2C payout requests handed to the M-Pesa adapter.",
)

PayoutRepository = InMemoryPayoutRepository | PostgresPayoutRepository
LedgerRepository = InMemoryLedgerRepository | PostgresLedgerRepository

LEDGER_PAYOUT_DISBURSED = "payout_disbursed"


class B2CValidationError(ValueError):
    """Request failed domain validation before any Daraja call."""


class B2CService:
    """Commission → Payments B2C disbursement ([ADR-004], [ADR-007])."""

    def __init__(
        self,
        *,
        payouts: PayoutRepository,
        ledger: LedgerRepository,
        adapter: MpesaAdapter,
    ) -> None:
        self._payouts = payouts
        self._ledger = ledger
        self._adapter = adapter

    async def initiate(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        attendant_id: str,
        phone_number: str,
        amount_minor_units: int,
        originator_conversation_id: str,
    ) -> tuple[Payout, int]:
        if amount_minor_units <= 0:
            raise B2CValidationError("amount_minor_units must be positive")
        if not originator_conversation_id:
            raise B2CValidationError("originator_conversation_id is required")
        if idempotency_key != originator_conversation_id:
            raise B2CValidationError(
                "Idempotency-Key must equal originator_conversation_id"
            )

        amount_whole_kes = to_whole_kes(amount_minor_units)
        if amount_whole_kes < 1:
            raise B2CValidationError("amount must round to at least 1 whole KES")

        existing = await self._payouts.get_by_tenant_and_originator(
            tenant_id, originator_conversation_id
        )
        if existing is not None:
            return existing, 200

        now = datetime.now(UTC)
        payout = Payout(
            id=uuid4(),
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            originator_conversation_id=originator_conversation_id,
            attendant_id=attendant_id,
            phone_number=phone_number,
            amount_minor_units=amount_minor_units,
            amount_whole_kes=amount_whole_kes,
            state=PayoutState.PENDING.value,
            created_at=now,
            updated_at=now,
        )
        payout = await self._payouts.save(payout)

        with traced(
            "payments.b2c_initiate",
            amount_minor_units=amount_minor_units,
            amount_whole_kes=amount_whole_kes,
        ):
            try:
                response = await self._adapter.initiate_b2c(
                    B2CRequest(
                        tenant_id=tenant_id,
                        idempotency_key=idempotency_key,
                        phone_number=phone_number,
                        amount_whole_kes=amount_whole_kes,
                        originator_conversation_id=originator_conversation_id,
                    )
                )
            except MpesaTimeoutError:
                # Timeout ≠ decline — leave pending for ResultURL / retry.
                b2c_initiated.add(1, {"result": "timeout"})
                return payout, 202

            assert_payout_transition(PayoutState.PENDING, PayoutState.SUBMITTED)
            payout.state = PayoutState.SUBMITTED.value
            payout.conversation_id = response.conversation_id
            payout.updated_at = datetime.now(UTC)
            payout = await self._payouts.update(payout)
            b2c_initiated.add(1, {"result": "accepted"})
            return payout, 202

    async def apply_result(
        self,
        *,
        conversation_id: str,
        success: bool,
        result_desc: str | None = None,
    ) -> Payout:
        """Apply Daraja B2C ResultURL outcome — one ledger effect on success."""
        payout = await self._payouts.get_by_conversation_id(conversation_id)
        if payout is None:
            raise B2CValidationError("payout not found for B2C result")

        if is_payout_terminal(payout.payout_state):
            return payout

        current = payout.payout_state
        if current is PayoutState.PENDING:
            # Result arrived after initiate timed out before submitted.
            assert_payout_transition(PayoutState.PENDING, PayoutState.SUBMITTED)
            payout.state = PayoutState.SUBMITTED.value
            payout.updated_at = datetime.now(UTC)
            payout = await self._payouts.update(payout)
            current = PayoutState.SUBMITTED

        now = datetime.now(UTC)
        if success:
            assert_payout_transition(current, PayoutState.COMPLETED)
            payout.state = PayoutState.COMPLETED.value
            payout.completed_at = now
            payout.updated_at = now
            payout = await self._payouts.update(payout)
            if await self._ledger.count_for_payout(payout.id, LEDGER_PAYOUT_DISBURSED) == 0:
                await self._ledger.append(
                    PaymentLedgerEntry(
                        tenant_id=payout.tenant_id,
                        payment_id=None,
                        payout_id=payout.id,
                        entry_type=LEDGER_PAYOUT_DISBURSED,
                        amount_minor_units=from_whole_kes(payout.amount_whole_kes),
                        created_at=now,
                    )
                )
        else:
            assert_payout_transition(current, PayoutState.FAILED)
            payout.state = PayoutState.FAILED.value
            payout.failure_reason = result_desc or "b2c_failed"
            payout.updated_at = now
            payout = await self._payouts.update(payout)

        return payout
