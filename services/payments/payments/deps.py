from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession
from tillflow_shared import MpesaSettings, create_mpesa_adapter
from tillflow_shared.idempotency import (
    IdempotencyHandle,
    IdempotencyRequiredError,
    IdempotencyService,
    InMemoryIdempotencyStore,
)
from tillflow_shared.idempotency.store import IdempotencyStore
from tillflow_shared.mpesa.adapter import MpesaAdapter

from payments.clients.pos import HttpPosClient, PosClient
from payments.config import settings
from payments.db import SessionLocal
from payments.idempotency.postgres_store import PostgresIdempotencyStore
from payments.outbox import InMemoryOutbox
from payments.repositories.memory import InMemoryPaymentRepository
from payments.repositories.memory_settlement import (
    InMemoryCallbackRepository,
    InMemoryLedgerRepository,
)
from payments.repositories.payout_memory import InMemoryPayoutRepository
from payments.repositories.payout_postgres import PostgresPayoutRepository
from payments.repositories.postgres import PostgresPaymentRepository
from payments.repositories.postgres_settlement import (
    PostgresCallbackRepository,
    PostgresLedgerRepository,
)
from payments.services.b2c_service import B2CService
from payments.services.callback_service import CallbackService
from payments.services.reconciliation_service import ReconciliationService
from payments.services.stk_service import StkService

_memory_payments = InMemoryPaymentRepository()
_memory_payouts = InMemoryPayoutRepository()
_memory_callbacks = InMemoryCallbackRepository()
_memory_ledger = InMemoryLedgerRepository()
_memory_idempotency = InMemoryIdempotencyStore()
_memory_outbox = InMemoryOutbox()
_adapter: MpesaAdapter | None = None


def get_mpesa_adapter() -> MpesaAdapter:
    global _adapter
    if _adapter is None:
        _adapter = create_mpesa_adapter(
            MpesaSettings(MPESA_ADAPTER=settings.mpesa_adapter)  # type: ignore[call-arg]
        )
    return _adapter


def reset_runtime_state() -> None:
    """Clear in-memory stores between tests."""
    global _adapter
    _memory_payments.clear()
    _memory_payouts.clear()
    _memory_callbacks.clear()
    _memory_ledger.clear()
    _memory_idempotency.clear()
    _memory_outbox.clear()
    _adapter = None


async def get_db_session() -> AsyncIterator[AsyncSession | None]:
    if SessionLocal is None:
        yield None
        return
    async with SessionLocal() as session:
        yield session


def get_payment_repository(
    session: AsyncSession | None = Depends(get_db_session),
) -> InMemoryPaymentRepository | PostgresPaymentRepository:
    if session is None:
        return _memory_payments
    return PostgresPaymentRepository(session)


def get_callback_repository(
    session: AsyncSession | None = Depends(get_db_session),
) -> InMemoryCallbackRepository | PostgresCallbackRepository:
    if session is None:
        return _memory_callbacks
    return PostgresCallbackRepository(session)


def get_ledger_repository(
    session: AsyncSession | None = Depends(get_db_session),
) -> InMemoryLedgerRepository | PostgresLedgerRepository:
    if session is None:
        return _memory_ledger
    return PostgresLedgerRepository(session)


def get_pos_client() -> PosClient | None:
    """``None`` when POS_BASE_URL is unset — payments still settles, silently."""
    if not settings.pos_base_url:
        return None
    return HttpPosClient(settings.pos_base_url)


def get_outbox() -> InMemoryOutbox:
    return _memory_outbox


def get_idempotency_store(
    session: AsyncSession | None = Depends(get_db_session),
) -> IdempotencyStore:
    if session is None:
        return _memory_idempotency
    return PostgresIdempotencyStore(session)


async def get_idempotency_handle(
    store: IdempotencyStore = Depends(get_idempotency_store),
    tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> IdempotencyHandle:
    if not tenant_id or not idempotency_key:
        raise IdempotencyRequiredError("X-Tenant-Id and Idempotency-Key are required")
    service = IdempotencyService(store, service_name=settings.service_name)
    return IdempotencyHandle(service, tenant_id, idempotency_key)


def get_stk_service(
    repository: InMemoryPaymentRepository | PostgresPaymentRepository = Depends(
        get_payment_repository
    ),
    adapter: MpesaAdapter = Depends(get_mpesa_adapter),
    outbox: InMemoryOutbox = Depends(get_outbox),
) -> StkService:
    return StkService(repository=repository, adapter=adapter, outbox=outbox)


def get_callback_service(
    payments: InMemoryPaymentRepository | PostgresPaymentRepository = Depends(
        get_payment_repository
    ),
    callbacks: InMemoryCallbackRepository | PostgresCallbackRepository = Depends(
        get_callback_repository
    ),
    ledger: InMemoryLedgerRepository | PostgresLedgerRepository = Depends(get_ledger_repository),
    adapter: MpesaAdapter = Depends(get_mpesa_adapter),
    pos: PosClient | None = Depends(get_pos_client),
) -> CallbackService:
    return CallbackService(
        payments=payments,
        callbacks=callbacks,
        ledger=ledger,
        adapter=adapter,
        expected_callback_secret=settings.mpesa_callback_secret,
        pos=pos,
    )


def get_reconciliation_service(
    payments: InMemoryPaymentRepository | PostgresPaymentRepository = Depends(
        get_payment_repository
    ),
    ledger: InMemoryLedgerRepository | PostgresLedgerRepository = Depends(get_ledger_repository),
    adapter: MpesaAdapter = Depends(get_mpesa_adapter),
    outbox: InMemoryOutbox = Depends(get_outbox),
    pos: PosClient | None = Depends(get_pos_client),
) -> ReconciliationService:
    return ReconciliationService(
        payments=payments,
        ledger=ledger,
        adapter=adapter,
        outbox=outbox,
        pos=pos,
    )


def get_payout_repository(
    session: AsyncSession | None = Depends(get_db_session),
) -> InMemoryPayoutRepository | PostgresPayoutRepository:
    if session is None:
        return _memory_payouts
    return PostgresPayoutRepository(session)


def get_b2c_service(
    payouts: InMemoryPayoutRepository | PostgresPayoutRepository = Depends(get_payout_repository),
    ledger: InMemoryLedgerRepository | PostgresLedgerRepository = Depends(get_ledger_repository),
    adapter: MpesaAdapter = Depends(get_mpesa_adapter),
) -> B2CService:
    return B2CService(payouts=payouts, ledger=ledger, adapter=adapter)
