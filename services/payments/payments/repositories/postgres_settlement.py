from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from payments.domain.models import PaymentCallback, PaymentLedgerEntry


class PostgresCallbackRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def try_insert(self, callback: PaymentCallback) -> bool:
        stmt = (
            insert(PaymentCallback)
            .values(
                tenant_id=callback.tenant_id,
                payment_id=callback.payment_id,
                merchant_request_id=callback.merchant_request_id,
                checkout_request_id=callback.checkout_request_id,
                result_code=callback.result_code,
                raw_payload=callback.raw_payload,
                received_at=callback.received_at,
            )
            .on_conflict_do_nothing(
                index_elements=["merchant_request_id", "checkout_request_id"],
            )
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return (result.rowcount or 0) == 1


class PostgresLedgerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, entry: PaymentLedgerEntry) -> PaymentLedgerEntry:
        self._session.add(entry)
        await self._session.commit()
        await self._session.refresh(entry)
        return entry

    async def count_for_payment(self, payment_id: UUID, entry_type: str) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(PaymentLedgerEntry)
            .where(
                PaymentLedgerEntry.payment_id == payment_id,
                PaymentLedgerEntry.entry_type == entry_type,
            )
        )
        return int(result.scalar_one())

    async def count_for_payout(self, payout_id: UUID, entry_type: str) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(PaymentLedgerEntry)
            .where(
                PaymentLedgerEntry.payout_id == payout_id,
                PaymentLedgerEntry.entry_type == entry_type,
            )
        )
        return int(result.scalar_one())

    async def list_for_payment(self, payment_id: UUID) -> list[PaymentLedgerEntry]:
        result = await self._session.execute(
            select(PaymentLedgerEntry).where(PaymentLedgerEntry.payment_id == payment_id)
        )
        return list(result.scalars().all())

    async def list_for_payout(self, payout_id: UUID) -> list[PaymentLedgerEntry]:
        result = await self._session.execute(
            select(PaymentLedgerEntry).where(PaymentLedgerEntry.payout_id == payout_id)
        )
        return list(result.scalars().all())
