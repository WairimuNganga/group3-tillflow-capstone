from __future__ import annotations

import uuid
from dataclasses import dataclass

from tillflow_shared.otel.middleware import traced

from pos.domain.models import Sale, SaleItem
from pos.domain.state import SaleStatus, assert_sale_transition
from pos.repositories.errors import AlreadyExistsError
from pos.repositories.memory import InMemoryPosRepository
from pos.repositories.postgres import PostgresPosRepository

PosRepository = InMemoryPosRepository | PostgresPosRepository


@dataclass(frozen=True)
class SaleLine:
    name: str
    quantity: int
    unit_price_minor: int


class SaleService:
    """Create sales idempotently and drive the sale state machine (ADR-004)."""

    def __init__(self, repository: PosRepository) -> None:
        self._repo = repository

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
