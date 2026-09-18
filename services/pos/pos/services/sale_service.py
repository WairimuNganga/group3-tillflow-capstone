from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from tillflow_shared.otel.middleware import traced

from pos.clients.payments import PaymentsClient, StkResult
from pos.domain.models import Sale, SaleItem
from pos.domain.state import (
    InvalidStateTransitionError,
    SaleStatus,
    assert_sale_transition,
    is_sale_terminal,
)
from pos.repositories.errors import AlreadyExistsError
from pos.repositories.memory import InMemoryPosRepository
from pos.repositories.postgres import PostgresPosRepository

PosRepository = InMemoryPosRepository | PostgresPosRepository


class AmountMismatchError(Exception):
    """Reported payment amount does not equal the sale total."""


class PhoneNumberRequiredError(Exception):
    """No customer phone number on the sale and none supplied."""


@dataclass(frozen=True)
class SaleLine:
    name: str
    quantity: int
    unit_price_minor: int


class SaleService:
    """Create sales idempotently and drive the sale state machine (ADR-004)."""

    def __init__(
        self, repository: PosRepository, payments: PaymentsClient | None = None
    ) -> None:
        self._repo = repository
        self._payments = payments

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        idempotency_key: str,
        till_id: uuid.UUID,
        attendant_id: uuid.UUID,
        lines: list[SaleLine],
        currency: str = "KES",
        customer_msisdn: str | None = None,
    ) -> tuple[Sale, bool]:
        """Returns ``(sale, created)``. Replaying an idempotency key returns the
        original sale with ``created=False`` — never a second sale."""
        # Fast path: key already used.
        existing = await self._repo.get_sale_by_idempotency(tenant_id, idempotency_key)
        if existing is not None:
            return existing, False

        items = [
            SaleItem(
                tenant_id=tenant_id,
                name=line.name,
                quantity=line.quantity,
                unit_price_minor=line.unit_price_minor,
                line_total_minor=line.quantity * line.unit_price_minor,
            )
            for line in lines
        ]
        sale = Sale(
            tenant_id=tenant_id,
            till_id=till_id,
            attendant_id=attendant_id,
            idempotency_key=idempotency_key,
            status=SaleStatus.PENDING.value,
            currency=currency,
            total_minor=sum(i.line_total_minor for i in items),
            customer_msisdn=customer_msisdn,
            items=items,
        )

        with traced("pos.create_sale", total_minor=sale.total_minor, item_count=len(items)):
            try:
                created = await self._repo.create_sale(sale)
            except AlreadyExistsError:
                # Lost a race on the same key: return the winner.
                winner = await self._repo.get_sale_by_idempotency(tenant_id, idempotency_key)
                if winner is None:  # pragma: no cover - defensive
                    raise
                return winner, False
        return created, True

    async def get(self, *, tenant_id: uuid.UUID, sale_id: uuid.UUID) -> Sale | None:
        return await self._repo.get_sale(tenant_id, sale_id)

    async def list(self, *, tenant_id: uuid.UUID) -> list[Sale]:
        return await self._repo.list_sales(tenant_id)

    async def transition(
        self, *, tenant_id: uuid.UUID, sale_id: uuid.UUID, target: SaleStatus
    ) -> Sale | None:
        """Move a sale to ``target``. Returns ``None`` if the sale isn't visible
        to this tenant. Same-state is an idempotent no-op; illegal moves raise
        ``InvalidStateTransitionError``."""
        sale = await self._repo.get_sale(tenant_id, sale_id)
        if sale is None:
            return None

        current = sale.sale_status
        if current == target:
            return sale  # idempotent no-op (e.g. duplicated payments callback)

        assert_sale_transition(current, target)
        sale.status = target.value
        return await self._repo.update_sale(sale)

    async def request_payment(
        self, *, tenant_id: uuid.UUID, sale_id: uuid.UUID, phone_number: str | None = None
    ) -> tuple[Sale, StkResult] | None:
        """Ask Payments to collect for this sale (POS -> Payments, hop 1).

        Moves the sale to ``awaiting_payment`` *before* the handoff, so a sale is
        never left looking unpaid while a prompt is on the customer's phone.
        Retrying is safe: Payments dedupes on the sale-derived idempotency key,
        so the customer is not prompted twice. Returns ``None`` if the sale is
        not visible to this tenant.
        """
        if self._payments is None:  # pragma: no cover - guarded at the API layer
            raise RuntimeError("payments client is not configured")

        sale = await self._repo.get_sale(tenant_id, sale_id)
        if sale is None:
            return None

        current = sale.sale_status
        if current not in (SaleStatus.PENDING, SaleStatus.AWAITING_PAYMENT):
            raise InvalidStateTransitionError(
                f"cannot request payment for a {current.value} sale"
            )

        msisdn = phone_number or sale.customer_msisdn
        if not msisdn:
            raise PhoneNumberRequiredError("no customer phone number for this sale")

        if current is SaleStatus.PENDING:
            sale.status = SaleStatus.AWAITING_PAYMENT.value
            sale = await self._repo.update_sale(sale)

        with traced("pos.request_payment", sale_id=str(sale_id)):
            result = await self._payments.initiate_stk(
                tenant_id=tenant_id,
                sale_id=sale.id,
                phone_number=msisdn,
                amount_minor_units=sale.total_minor,
            )
        return sale, result

    async def apply_payment_result(
        self,
        *,
        tenant_id: uuid.UUID,
        sale_id: uuid.UUID,
        result: SaleStatus,
        payment_id: uuid.UUID,
        amount_minor_units: int | None = None,
        mpesa_receipt: str | None = None,
    ) -> tuple[Sale, bool] | None:
        """Apply the outcome Payments reports (Payments -> POS, hop 2).

        Returns ``(sale, changed)``; ``changed=False`` for a replayed result, so a
        duplicated M-Pesa callback produces exactly one state change. Returns
        ``None`` if the sale is not visible to this tenant.
        """
        sale = await self._repo.get_sale(tenant_id, sale_id)
        if sale is None:
            return None

        # Guard against settling a sale with the wrong amount — the money
        # crossing the M-Pesa boundary must be the money that was rung up.
        if amount_minor_units is not None and amount_minor_units != sale.total_minor:
            raise AmountMismatchError(
                f"payment is {amount_minor_units} minor units, sale total is {sale.total_minor}"
            )

        current = sale.sale_status
        if current is result:
            return sale, False  # replayed callback / reconciliation

        if is_sale_terminal(current):
            raise InvalidStateTransitionError(
                f"sale is already {current.value}; cannot mark it {result.value}"
            )

        # A result can arrive for a sale still 'pending' (the handoff response was
        # lost, or Payments settled very fast). Walk the legal path rather than
        # jumping states.
        if current is SaleStatus.PENDING:
            sale.status = SaleStatus.AWAITING_PAYMENT.value
            current = SaleStatus.AWAITING_PAYMENT

        assert_sale_transition(current, result)
        sale.status = result.value
        sale.payment_id = payment_id
        if result is SaleStatus.PAID:
            sale.mpesa_receipt = mpesa_receipt
            sale.paid_at = datetime.now(UTC)
        return await self._repo.update_sale(sale), True
