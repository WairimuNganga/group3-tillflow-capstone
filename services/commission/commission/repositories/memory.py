from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime

from commission.domain.models import CloseRun, CommissionLedgerEntry, PayoutIntent
from commission.domain.state import PayoutIntentState
from commission.repositories.reads import (
    AttendantContact,
    AttendantRate,
    AttendantReader,
    PaidSaleRow,
    PaidSalesReader,
    RateReader,
)
from commission.timeutil import to_eat_date


class InMemoryCloseRunRepository:
    def __init__(self) -> None:
        self._by_period: dict[date, CloseRun] = {}

    def clear(self) -> None:
        self._by_period.clear()

    async def get_by_period(self, payout_period: date) -> CloseRun | None:
        run = self._by_period.get(payout_period)
        return deepcopy(run) if run else None

    async def save(self, run: CloseRun) -> CloseRun:
        self._by_period[run.payout_period] = deepcopy(run)
        return deepcopy(run)


class InMemoryLedgerRepository:
    def __init__(self) -> None:
        self._rows: list[CommissionLedgerEntry] = []
        self._next_id = 1

    def clear(self) -> None:
        self._rows.clear()
        self._next_id = 1

    async def try_insert(self, entry: CommissionLedgerEntry) -> bool:
        key = (entry.tenant_id, entry.payout_period, entry.attendant_id, entry.sale_id)
        for existing in self._rows:
            ek = (
                existing.tenant_id,
                existing.payout_period,
                existing.attendant_id,
                existing.sale_id,
            )
            if ek == key:
                return False
        if entry.id is None or entry.id == 0:
            entry.id = self._next_id
            self._next_id += 1
        self._rows.append(deepcopy(entry))
        return True

    async def list_for_period(self, payout_period: date) -> list[CommissionLedgerEntry]:
        return [deepcopy(e) for e in self._rows if e.payout_period == payout_period]

    async def sum_for_attendant(
        self, tenant_id: str, payout_period: date, attendant_id: str
    ) -> int:
        return sum(
            e.commission_minor_units
            for e in self._rows
            if e.tenant_id == tenant_id
            and e.payout_period == payout_period
            and e.attendant_id == attendant_id
        )


class InMemoryPayoutIntentRepository:
    def __init__(self) -> None:
        self._by_key: dict[tuple[str, date, str], PayoutIntent] = {}

    def clear(self) -> None:
        self._by_key.clear()

    async def get(
        self, tenant_id: str, payout_period: date, attendant_id: str
    ) -> PayoutIntent | None:
        intent = self._by_key.get((tenant_id, payout_period, attendant_id))
        return deepcopy(intent) if intent else None

    async def upsert(self, intent: PayoutIntent) -> PayoutIntent:
        key = (intent.tenant_id, intent.payout_period, intent.attendant_id)
        existing = self._by_key.get(key)
        if existing is not None and existing.state == PayoutIntentState.COMPLETED.value:
            return deepcopy(existing)
        if existing is not None:
            intent.id = existing.id
            if existing.payments_payout_id and not intent.payments_payout_id:
                intent.payments_payout_id = existing.payments_payout_id
            if existing.state == PayoutIntentState.SUBMITTED.value and intent.state == (
                PayoutIntentState.PENDING.value
            ):
                intent.state = existing.state
                intent.payments_payout_id = existing.payments_payout_id
        self._by_key[key] = deepcopy(intent)
        return deepcopy(intent)

    async def list_pending(self, payout_period: date) -> list[PayoutIntent]:
        return [
            deepcopy(i)
            for i in self._by_key.values()
            if i.payout_period == payout_period
            and i.state
            in {PayoutIntentState.PENDING.value, PayoutIntentState.FAILED.value}
        ]

    async def list_for_period(self, payout_period: date) -> list[PayoutIntent]:
        return [
            deepcopy(i) for i in self._by_key.values() if i.payout_period == payout_period
        ]

    async def list_for_tenant(
        self,
        tenant_id: str,
        *,
        attendant_id: str | None = None,
        state: str | None = None,
    ) -> list[PayoutIntent]:
        rows = [
            deepcopy(i)
            for i in self._by_key.values()
            if i.tenant_id == tenant_id
            and (attendant_id is None or i.attendant_id == attendant_id)
            and (state is None or i.state == state)
        ]
        rows.sort(key=lambda i: (i.payout_period, i.updated_at), reverse=True)
        return rows


class InMemoryPaidSalesReader(PaidSalesReader):
    def __init__(self) -> None:
        self.rows: list[PaidSaleRow] = []

    def clear(self) -> None:
        self.rows.clear()

    def seed(self, *rows: PaidSaleRow) -> None:
        self.rows.extend(rows)

    async def list_paid_in_period(self, payout_period: date) -> list[PaidSaleRow]:
        return [
            r
            for r in self.rows
            if to_eat_date(r.settled_at) == payout_period
        ]


class InMemoryRateReader(RateReader):
    def __init__(self) -> None:
        self.rates: list[AttendantRate] = []

    def clear(self) -> None:
        self.rates.clear()

    def seed(self, *rates: AttendantRate) -> None:
        self.rates.extend(rates)

    async def rate_as_of(
        self, tenant_id: str, attendant_id: str, as_of: datetime
    ) -> AttendantRate | None:
        candidates = [
            r
            for r in self.rates
            if r.tenant_id == tenant_id
            and r.attendant_id == attendant_id
            and r.effective_from <= as_of
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r.effective_from)


class InMemoryAttendantReader(AttendantReader):
    def __init__(self) -> None:
        self.by_key: dict[tuple[str, str], AttendantContact] = {}

    def clear(self) -> None:
        self.by_key.clear()

    def seed(self, *contacts: AttendantContact) -> None:
        for c in contacts:
            self.by_key[(c.tenant_id, c.attendant_id)] = c

    async def get(self, tenant_id: str, attendant_id: str) -> AttendantContact | None:
        return self.by_key.get((tenant_id, attendant_id))
