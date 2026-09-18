"""Postgres-backed POS repository (used when DATABASE_URL is set).

The request transaction and the ``app.current_tenant_id`` GUC are owned by the
session dependency (``pos.deps.get_db_session``); these methods only read and
``flush``. Reads still filter by ``tenant_id`` explicitly — RLS is the backstop,
not a substitute (ADR-005).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pos.domain.models import Sale, Tenant, Till, User
from pos.repositories.errors import AlreadyExistsError, InvalidReferenceError

_PG_UNIQUE_VIOLATION = "23505"
_PG_FK_VIOLATION = "23503"
_SET_TENANT = text("SELECT set_config('app.current_tenant_id', :tid, true)")


def _translate(exc: IntegrityError) -> Exception:
    state = getattr(getattr(exc, "orig", None), "sqlstate", None)
    if state == _PG_UNIQUE_VIOLATION:
        return AlreadyExistsError(str(exc.orig))
    if state == _PG_FK_VIOLATION:
        return InvalidReferenceError(str(exc.orig))
    return exc


class PostgresPosRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def set_tenant(self, tenant_id: uuid.UUID) -> None:
        """Bind the tenant GUC for the current transaction (onboarding path)."""
        await self._session.execute(_SET_TENANT, {"tid": str(tenant_id)})

    async def _flush(self, obj: object) -> None:
        self._session.add(obj)
        try:
            async with self._session.begin_nested():
                await self._session.flush()
        except IntegrityError as exc:
            raise _translate(exc) from exc

    async def create_tenant(self, tenant: Tenant) -> Tenant:
        await self._flush(tenant)
        await self._session.refresh(tenant)
        return tenant

    async def create_user(self, user: User) -> User:
        await self._flush(user)
        await self._session.refresh(user)
        return user

    async def create_till(self, till: Till) -> Till:
        await self._flush(till)
        await self._session.refresh(till)
        return till

    async def get_sale_by_idempotency(
        self, tenant_id: uuid.UUID, idempotency_key: str
    ) -> Sale | None:
        result = await self._session.execute(
            select(Sale).where(
                Sale.tenant_id == tenant_id, Sale.idempotency_key == idempotency_key
            )
        )
        return result.scalar_one_or_none()

    async def create_sale(self, sale: Sale) -> Sale:
        await self._flush(sale)
        await self._session.refresh(sale, ["created_at", "status"])
        return sale

    async def get_sale(self, tenant_id: uuid.UUID, sale_id: uuid.UUID) -> Sale | None:
        result = await self._session.execute(
            select(Sale).where(Sale.tenant_id == tenant_id, Sale.id == sale_id)
        )
        return result.scalar_one_or_none()

    async def list_sales(self, tenant_id: uuid.UUID) -> list[Sale]:
        result = await self._session.execute(
            select(Sale).where(Sale.tenant_id == tenant_id).order_by(Sale.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_sale(self, sale: Sale) -> Sale:
        await self._session.flush()
        await self._session.refresh(sale)
        return sale
