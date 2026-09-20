from __future__ import annotations

import uuid
from datetime import datetime

from pos.domain.models import CommissionRate, Tenant, Till, User
from pos.repositories.memory import InMemoryPosRepository
from pos.repositories.postgres import PostgresPosRepository

PosRepository = InMemoryPosRepository | PostgresPosRepository


class TenantService:
    """Tenant onboarding: the owner configures the till and attendants."""

    def __init__(self, repository: PosRepository) -> None:
        self._repo = repository

    async def onboard(
        self, *, name: str, owner_phone: str, owner_name: str
    ) -> tuple[Tenant, User]:
        tenant_id = uuid.uuid4()
        # The tenant id is minted here, so set the GUC ourselves — there is no
        # X-Tenant-Id header on this call (RLS WITH CHECK needs it).
        await self._repo.set_tenant(tenant_id)

        tenant = await self._repo.create_tenant(Tenant(id=tenant_id, name=name))
        owner = await self._repo.create_user(
            User(tenant_id=tenant_id, phone=owner_phone, display_name=owner_name, role="owner")
        )
        return tenant, owner

    async def add_till(self, *, tenant_id: uuid.UUID, name: str, shortcode: str) -> Till:
        return await self._repo.create_till(
            Till(tenant_id=tenant_id, name=name, shortcode=shortcode)
        )

    async def add_attendant(
        self, *, tenant_id: uuid.UUID, phone: str, display_name: str
    ) -> User:
        return await self._repo.create_user(
            User(tenant_id=tenant_id, phone=phone, display_name=display_name, role="attendant")
        )

    async def set_commission_rate(
        self,
        *,
        tenant_id: uuid.UUID,
        attendant_id: uuid.UUID,
        rate_bps: int,
        effective_from: datetime | None = None,
    ) -> CommissionRate:
        rate = CommissionRate(
            tenant_id=tenant_id,
            attendant_id=attendant_id,
            rate_bps=rate_bps,
        )
        if effective_from is not None:
            rate.effective_from = effective_from
        return await self._repo.create_commission_rate(rate)

    async def list_commission_rates(
        self, *, tenant_id: uuid.UUID, attendant_id: uuid.UUID | None = None
    ) -> list[CommissionRate]:
        return await self._repo.list_commission_rates(tenant_id, attendant_id)
