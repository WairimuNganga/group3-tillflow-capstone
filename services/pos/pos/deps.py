from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tillflow_shared.otel import get_idempotency_key, get_tenant_id

from pos import db
from pos.clients.payments import HttpPaymentsClient, PaymentsClient
from pos.config import settings
from pos.repositories.memory import InMemoryPosRepository
from pos.repositories.postgres import PostgresPosRepository
from pos.services.sale_service import SaleService
from pos.services.tenant_service import TenantService

PosRepository = InMemoryPosRepository | PostgresPosRepository

_memory_repo = InMemoryPosRepository()
_SET_TENANT = text("SELECT set_config('app.current_tenant_id', :tid, true)")


def reset_runtime_state() -> None:
    """Clear in-memory stores between tests."""
    _memory_repo.clear()


async def get_db_session() -> AsyncIterator[AsyncSession | None]:
    """A request-scoped session in one transaction with the tenant GUC set, or
    ``None`` when no database is configured (in-memory mode)."""
    if db.SessionLocal is None:
        yield None
        return
    async with db.SessionLocal() as session, session.begin():
        tenant_id = get_tenant_id()
        if tenant_id:
            await session.execute(_SET_TENANT, {"tid": tenant_id})
        yield session


SessionDep = Annotated[AsyncSession | None, Depends(get_db_session)]


def get_repository(session: SessionDep) -> PosRepository:
    if session is None:
        return _memory_repo
    return PostgresPosRepository(session)


RepositoryDep = Annotated[PosRepository, Depends(get_repository)]


def require_tenant(
    x_tenant_id: Annotated[
        str | None,
        Header(alias="X-Tenant-Id", description="Tenant (shop) id from POST /tenants"),
    ] = None,
) -> uuid.UUID:
    """The tenant for a tenant-scoped request, from ``X-Tenant-Id``.

    The shared middleware binds the same header to the request context (which is
    what sets the RLS GUC); declaring it here also documents it in /docs."""
    tenant_id = get_tenant_id() or x_tenant_id
    if not tenant_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Tenant-Id header is required")
    try:
        return uuid.UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Tenant-Id is not a valid uuid") from exc


def require_idempotency_key(
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", description="Unique per sale; retries reuse it"),
    ] = None,
) -> str:
    key = get_idempotency_key() or idempotency_key
    if not key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Idempotency-Key header is required")
    return key


def get_tenant_service(repo: RepositoryDep) -> TenantService:
    return TenantService(repo)


def get_payments_client() -> PaymentsClient | None:
    """``None`` when PAYMENTS_BASE_URL is unset — the pay action then 503s."""
    if not settings.payments_base_url:
        return None
    return HttpPaymentsClient(settings.payments_base_url)


PaymentsClientDep = Annotated["PaymentsClient | None", Depends(get_payments_client)]


def get_sale_service(repo: RepositoryDep, payments: PaymentsClientDep) -> SaleService:
    return SaleService(repo, payments)
