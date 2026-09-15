from __future__ import annotations

import asyncio
from copy import deepcopy
from uuid import UUID

from payments.domain.models import Payout


class InMemoryPayoutRepository:
    """Local/CI payout store until RDS is wired."""

    def __init__(self) -> None:
        self._by_id: dict[UUID, Payout] = {}
        self._lock = asyncio.Lock()

    async def get_by_tenant_and_originator(
        self, tenant_id: str, originator_conversation_id: str
    ) -> Payout | None:
        async with self._lock:
            for payout in self._by_id.values():
                if (
                    payout.tenant_id == tenant_id
                    and payout.originator_conversation_id == originator_conversation_id
                ):
                    return deepcopy(payout)
            return None

    async def get_by_id(self, payout_id: UUID) -> Payout | None:
        async with self._lock:
            payout = self._by_id.get(payout_id)
            return deepcopy(payout) if payout else None

    async def get_by_conversation_id(self, conversation_id: str) -> Payout | None:
        async with self._lock:
            for payout in self._by_id.values():
                if payout.conversation_id == conversation_id:
                    return deepcopy(payout)
            return None

    async def save(self, payout: Payout) -> Payout:
        async with self._lock:
            for existing in self._by_id.values():
                if (
                    existing.tenant_id == payout.tenant_id
                    and existing.originator_conversation_id == payout.originator_conversation_id
                ):
                    raise ValueError("payout already exists for tenant/originator")
            self._by_id[payout.id] = deepcopy(payout)
            return deepcopy(payout)

    async def update(self, payout: Payout) -> Payout:
        async with self._lock:
            if payout.id not in self._by_id:
                raise KeyError(f"payout not found: {payout.id}")
            self._by_id[payout.id] = deepcopy(payout)
            return deepcopy(payout)

    def clear(self) -> None:
        self._by_id.clear()
