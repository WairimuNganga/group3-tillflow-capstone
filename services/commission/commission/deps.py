from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from commission.clients.payments import FakePaymentsClient, PaymentsClient
from commission.config import settings
from commission.db import SessionLocal
from commission.repositories.memory import (
    InMemoryAttendantReader,
    InMemoryCloseRunRepository,
    InMemoryLedgerRepository,
    InMemoryPaidSalesReader,
    InMemoryPayoutIntentRepository,
    InMemoryRateReader,
)
from commission.repositories.postgres import (
    PostgresAttendantReader,
    PostgresCloseRunRepository,
    PostgresLedgerRepository,
    PostgresPaidSalesReader,
    PostgresPayoutIntentRepository,
    PostgresRateReader,
)
from commission.services.close_service import CloseService
from commission.services.payout_service import PayoutService
from commission.worker.queue import InMemoryPayoutQueue, PayoutQueue, SqsPayoutQueue

_memory_close_runs = InMemoryCloseRunRepository()
_memory_ledger = InMemoryLedgerRepository()
_memory_intents = InMemoryPayoutIntentRepository()
_memory_paid_sales = InMemoryPaidSalesReader()
_memory_rates = InMemoryRateReader()
_memory_attendants = InMemoryAttendantReader()
_memory_queue = InMemoryPayoutQueue()
_fake_payments = FakePaymentsClient()
_queue: PayoutQueue | None = None
_payments: PaymentsClient | None = None


def reset_runtime_state() -> None:
    """Clear in-memory stores between tests."""
    global _queue, _payments
    _memory_close_runs.clear()
    _memory_ledger.clear()
    _memory_intents.clear()
    _memory_paid_sales.clear()
    _memory_rates.clear()
    _memory_attendants.clear()
    _memory_queue.clear()
    _fake_payments.clear()
    _queue = None
    _payments = None


def get_queue() -> PayoutQueue:
    global _queue
    if _queue is None:
        if settings.payout_queue_url:
            _queue = SqsPayoutQueue(settings.payout_queue_url)
        else:
            _queue = _memory_queue
    return _queue


def get_payments_client() -> PaymentsClient:
    global _payments
    if _payments is None:
        if settings.payments_base_url:
            _payments = PaymentsClient(settings.payments_base_url)
        else:
            _payments = _fake_payments
    return _payments


async def get_db_session() -> AsyncIterator[AsyncSession | None]:
    if SessionLocal is None:
        yield None
        return
    async with SessionLocal() as session:
        yield session


def get_close_service(
    session: AsyncSession | None = Depends(get_db_session),
) -> CloseService:
    if session is None:
        return CloseService(
            close_runs=_memory_close_runs,
            ledger=_memory_ledger,
            intents=_memory_intents,
            paid_sales=_memory_paid_sales,
            rates=_memory_rates,
            attendants=_memory_attendants,
            queue=get_queue(),
        )
    return CloseService(
        close_runs=PostgresCloseRunRepository(session),
        ledger=PostgresLedgerRepository(session),
        intents=PostgresPayoutIntentRepository(session),
        paid_sales=PostgresPaidSalesReader(session),
        rates=PostgresRateReader(session),
        attendants=PostgresAttendantReader(session),
        queue=get_queue(),
    )


def get_payout_service(
    session: AsyncSession | None = Depends(get_db_session),
) -> PayoutService:
    if session is None:
        return PayoutService(intents=_memory_intents, payments=get_payments_client())
    return PayoutService(
        intents=PostgresPayoutIntentRepository(session),
        payments=get_payments_client(),
    )


def get_memory_paid_sales() -> InMemoryPaidSalesReader:
    return _memory_paid_sales


def get_memory_rates() -> InMemoryRateReader:
    return _memory_rates


def get_memory_attendants() -> InMemoryAttendantReader:
    return _memory_attendants


def get_memory_ledger() -> InMemoryLedgerRepository:
    return _memory_ledger


def get_memory_intents() -> InMemoryPayoutIntentRepository:
    return _memory_intents


def get_memory_close_runs() -> InMemoryCloseRunRepository:
    return _memory_close_runs


def get_memory_queue() -> InMemoryPayoutQueue:
    return _memory_queue


def get_fake_payments() -> FakePaymentsClient:
    return _fake_payments
