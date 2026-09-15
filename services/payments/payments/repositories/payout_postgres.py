from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from payments.domain.models import Payout


class PostgresPayoutRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_tenant_and_originator(
        self, tenant_id: str, originator_conversation_id: str
    ) -> Payout | None:
        result = await self._session.execute(
            select(Payout).where(
                Payout.tenant_id == tenant_id,
                Payout.originator_conversation_id == originator_conversation_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, payout_id: UUID) -> Payout | None:
        result = await self._session.execute(select(Payout).where(Payout.id == payout_id))
        return result.scalar_one_or_none()

    async def get_by_conversation_id(self, conversation_id: str) -> Payout | None:
        result = await self._session.execute(
            select(Payout).where(Payout.conversation_id == conversation_id)
        )
        return result.scalar_one_or_none()

    async def save(self, payout: Payout) -> Payout:
        self._session.add(payout)
        await self._session.commit()
        await self._session.refresh(payout)
        return payout

    async def update(self, payout: Payout) -> Payout:
        await self._session.merge(payout)
        await self._session.commit()
        await self._session.refresh(payout)
        return payout
