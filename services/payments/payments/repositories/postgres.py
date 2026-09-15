from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from payments.domain.models import Payment


class PostgresPaymentRepository:
    """Postgres-backed payment repository (used once DATABASE_URL is set)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_tenant_and_sale(self, tenant_id: str, sale_id: UUID) -> Payment | None:
        result = await self._session.execute(
            select(Payment).where(Payment.tenant_id == tenant_id, Payment.sale_id == sale_id)
        )
        return result.scalar_one_or_none()

    async def get_by_tenant_and_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> Payment | None:
        result = await self._session.execute(
            select(Payment).where(
                Payment.tenant_id == tenant_id,
                Payment.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_checkout_request_id(self, checkout_request_id: str) -> Payment | None:
        result = await self._session.execute(
            select(Payment).where(Payment.checkout_request_id == checkout_request_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, payment_id: UUID) -> Payment | None:
        result = await self._session.execute(select(Payment).where(Payment.id == payment_id))
        return result.scalar_one_or_none()

    async def save(self, payment: Payment) -> Payment:
        self._session.add(payment)
        await self._session.commit()
        await self._session.refresh(payment)
        return payment

    async def update(self, payment: Payment) -> Payment:
        await self._session.merge(payment)
        await self._session.commit()
        await self._session.refresh(payment)
        return payment
