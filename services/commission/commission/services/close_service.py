from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import uuid4

from tillflow_shared.otel import business_counter
from tillflow_shared.otel.middleware import traced

from commission.domain.models import CloseRun, CommissionLedgerEntry, PayoutIntent
from commission.domain.state import (
    CloseRunStatus,
    PayoutIntentState,
    commission_minor,
)
from commission.repositories.reads import AttendantReader, PaidSalesReader, RateReader
from commission.worker.queue import PayoutQueue

_log = logging.getLogger(__name__)

close_runs_total = business_counter(
    "commission_close_runs_total",
    "Daily close runs by outcome.",
)
ledger_lines_total = business_counter(
    "commission_ledger_lines_total",
    "Commission ledger lines written.",
)
amount_mismatch_total = business_counter(
    "commission_amount_mismatch_total",
    "Paid sale amount disagreed between payments and POS.",
)


class CloseRunRepository(Protocol):
    async def get_by_period(self, payout_period: date) -> CloseRun | None: ...
    async def save(self, run: CloseRun) -> CloseRun: ...


class LedgerRepository(Protocol):
    async def try_insert(self, entry: CommissionLedgerEntry) -> bool: ...
    async def list_for_period(self, payout_period: date) -> list[CommissionLedgerEntry]: ...
    async def sum_for_attendant(
        self, tenant_id: str, payout_period: date, attendant_id: str
    ) -> int: ...


class PayoutIntentRepository(Protocol):
    async def upsert(self, intent: PayoutIntent) -> PayoutIntent: ...
    async def list_pending(self, payout_period: date) -> list[PayoutIntent]: ...
    async def list_for_period(self, payout_period: date) -> list[PayoutIntent]: ...


@dataclass(frozen=True, slots=True)
class CloseResult:
    payout_period: date
    status: str
    ledger_lines_written: int
    intents_enqueued: int
    skipped_mismatch: int
    already_completed: bool = False


class CloseService:
    """Calc from paid sales → ledger → per-attendant payout intents + SQS fan-out."""

    def __init__(
        self,
        *,
        close_runs: CloseRunRepository,
        ledger: LedgerRepository,
        intents: PayoutIntentRepository,
        paid_sales: PaidSalesReader,
        rates: RateReader,
        attendants: AttendantReader,
        queue: PayoutQueue,
    ) -> None:
        self._close_runs = close_runs
        self._ledger = ledger
        self._intents = intents
        self._paid_sales = paid_sales
        self._rates = rates
        self._attendants = attendants
        self._queue = queue

    async def run(self, payout_period: date) -> CloseResult:
        with traced("commission.daily_close", payout_period=str(payout_period)):
            return await self._run(payout_period)

    async def _run(self, payout_period: date) -> CloseResult:
        existing = await self._close_runs.get_by_period(payout_period)
        already_completed = (
            existing is not None and existing.status == CloseRunStatus.COMPLETED.value
        )

        now = datetime.now(UTC)
        run = existing or CloseRun(
            id=uuid4(),
            payout_period=payout_period,
            status=CloseRunStatus.RUNNING.value,
            started_at=now,
        )
        run.status = CloseRunStatus.RUNNING.value
        await self._close_runs.save(run)

        sales = await self._paid_sales.list_paid_in_period(payout_period)
        written = 0
        skipped = 0
        attendant_keys: set[tuple[str, str]] = set()

        for sale in sales:
            if sale.pos_total_minor is not None and sale.pos_total_minor != sale.amount_minor_units:
                _log.warning(
                    "amount mismatch tenant=%s sale=%s payments=%s pos=%s",
                    sale.tenant_id,
                    sale.sale_id,
                    sale.amount_minor_units,
                    sale.pos_total_minor,
                )
                amount_mismatch_total.add(1, {"result": "skipped"})
                skipped += 1
                continue

            # Rate in effect at settlement time (not midnight — rates may be set mid-day).
            rate = await self._rates.rate_as_of(
                sale.tenant_id, sale.attendant_id, sale.settled_at
            )
            if rate is None:
                _log.warning(
                    "no rate for tenant=%s attendant=%s period=%s",
                    sale.tenant_id,
                    sale.attendant_id,
                    payout_period,
                )
                continue

            owed = commission_minor(sale.amount_minor_units, rate.rate_bps)
            inserted = await self._ledger.try_insert(
                CommissionLedgerEntry(
                    tenant_id=sale.tenant_id,
                    payout_period=payout_period,
                    attendant_id=sale.attendant_id,
                    sale_id=sale.sale_id,
                    payment_id=sale.payment_id,
                    sale_amount_minor_units=sale.amount_minor_units,
                    rate_bps=rate.rate_bps,
                    commission_minor_units=owed,
                    created_at=now,
                )
            )
            if inserted:
                written += 1
                ledger_lines_total.add(1, {"result": "written"})
            attendant_keys.add((sale.tenant_id, sale.attendant_id))

        # Also include attendants that already have ledger lines (replay path).
        for entry in await self._ledger.list_for_period(payout_period):
            attendant_keys.add((entry.tenant_id, entry.attendant_id))

        enqueued = 0
        for tenant_id, attendant_id in sorted(attendant_keys):
            contact = await self._attendants.get(tenant_id, attendant_id)
            if contact is None:
                _log.warning("no attendant contact tenant=%s id=%s", tenant_id, attendant_id)
                continue
            total = await self._ledger.sum_for_attendant(tenant_id, payout_period, attendant_id)
            if total <= 0:
                continue
            intent = PayoutIntent(
                id=uuid4(),
                tenant_id=tenant_id,
                payout_period=payout_period,
                attendant_id=attendant_id,
                phone_number=contact.phone_number,
                amount_minor_units=total,
                state=PayoutIntentState.PENDING.value,
                created_at=now,
                updated_at=now,
            )
            saved = await self._intents.upsert(intent)
            if saved.state in {
                PayoutIntentState.COMPLETED.value,
                PayoutIntentState.SUBMITTED.value,
            }:
                continue
            await self._queue.send(
                {
                    "event": "commission.attendant_payout.requested",
                    "tenant_id": tenant_id,
                    "payout_period": payout_period.isoformat(),
                    "attendant_id": attendant_id,
                }
            )
            enqueued += 1

        run.status = CloseRunStatus.COMPLETED.value
        run.completed_at = datetime.now(UTC)
        await self._close_runs.save(run)
        close_runs_total.add(
            1, {"result": "replay" if already_completed else "completed"}
        )
        return CloseResult(
            payout_period=payout_period,
            status=run.status,
            ledger_lines_written=written,
            intents_enqueued=enqueued,
            skipped_mismatch=skipped,
            already_completed=already_completed and written == 0,
        )
