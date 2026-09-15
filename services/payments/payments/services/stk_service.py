from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from payments.domain.models import Payment
from payments.domain.state import PaymentState, assert_payment_transition
from payments.outbox import InMemoryOutbox
from payments.repositories.memory import InMemoryPaymentRepository
from payments.repositories.postgres import PostgresPaymentRepository
from tillflow_shared.money import to_whole_kes
from tillflow_shared.mpesa.adapter import MpesaAdapter
from tillflow_shared.mpesa.exceptions import MpesaTimeoutError
from tillflow_shared.mpesa.scenarios import FakeScenario
from tillflow_shared.mpesa.types import StkPushRequest
from tillflow_shared.otel import business_counter
from tillflow_shared.otel.middleware import traced

stk_initiated = business_counter(
    "payments_stk_initiated_total",
    "STK push requests handed to the M-Pesa adapter.",
)

PaymentRepository = InMemoryPaymentRepository | PostgresPaymentRepository


class StkValidationError(ValueError):
    """Request failed domain validation before any Daraja call."""


class StkService:
    """Initiate STK Push for a POS sale ([ADR-004], [ADR-007])."""

    def __init__(
        self,
        *,
        repository: PaymentRepository,
        adapter: MpesaAdapter,
        outbox: InMemoryOutbox,
    ) -> None:
        self._repository = repository
        self._adapter = adapter
        self._outbox = outbox

    async def initiate(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        sale_id: UUID,
        phone_number: str,
        amount_minor_units: int,
        fake_scenario: FakeScenario | None = None,
    ) -> tuple[Payment, int]:
        """Create or resume a payment and call Daraja.

        Returns ``(payment, http_status)``. Status is 202 for newly initiated /
        timed-out paths and 200 when returning an already-terminal payment.
        """
        if amount_minor_units <= 0:
            raise StkValidationError("amount_minor_units must be positive")

        amount_whole_kes = to_whole_kes(amount_minor_units)
        if amount_whole_kes < 1:
            raise StkValidationError("amount must round to at least 1 whole KES")

        existing = await self._repository.get_by_tenant_and_sale(tenant_id, sale_id)
        if existing is not None:
            return existing, 200

        existing_by_key = await self._repository.get_by_tenant_and_idempotency_key(
            tenant_id, idempotency_key
        )
        if existing_by_key is not None:
            return existing_by_key, 200

        now = datetime.now(UTC)
        payment = Payment(
            id=uuid4(),
            tenant_id=tenant_id,
            sale_id=sale_id,
            idempotency_key=idempotency_key,
            amount_minor_units=amount_minor_units,
            amount_whole_kes=amount_whole_kes,
            state=PaymentState.PENDING.value,
            phone_number=phone_number,
            created_at=now,
            updated_at=now,
        )
        payment = await self._repository.save(payment)

        with traced(
            "payments.stk_push",
            amount_minor_units=amount_minor_units,
            amount_whole_kes=amount_whole_kes,
        ):
            try:
                response = await self._adapter.initiate_stk_push(
                    StkPushRequest(
                        tenant_id=tenant_id,
                        idempotency_key=idempotency_key,
                        phone_number=phone_number,
                        amount_whole_kes=amount_whole_kes,
                        account_reference=idempotency_key,
                        fake_scenario=fake_scenario,
                    )
                )
            except MpesaTimeoutError as exc:
                # Timeout ≠ decline: keep IDs when known, enqueue reconciliation.
                assert_payment_transition(
                    PaymentState.PENDING, PaymentState.PENDING_RECONCILIATION
                )
                payment.state = PaymentState.PENDING_RECONCILIATION.value
                payment.merchant_request_id = exc.merchant_request_id
                payment.checkout_request_id = exc.checkout_request_id
                payment.updated_at = datetime.now(UTC)
                payment = await self._repository.update(payment)
                await self._outbox.enqueue_reconciliation(payment.id)
                stk_initiated.add(1, {"result": "timeout"})
                return payment, 202

            assert_payment_transition(PaymentState.PENDING, PaymentState.STK_SENT)
            payment.state = PaymentState.STK_SENT.value
            payment.merchant_request_id = response.merchant_request_id
            payment.checkout_request_id = response.checkout_request_id
            payment.updated_at = datetime.now(UTC)
            payment = await self._repository.update(payment)
            stk_initiated.add(1, {"result": "accepted"})
            return payment, 202
