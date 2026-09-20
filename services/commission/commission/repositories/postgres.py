from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text

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


class PostgresCloseRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_period(self, payout_period: date) -> CloseRun | None:
        result = await self._session.execute(
            select(CloseRun).where(CloseRun.payout_period == payout_period)
        )
        return result.scalar_one_or_none()

    async def save(self, run: CloseRun) -> CloseRun:
        merged = await self._session.merge(run)
        await self._session.commit()
        await self._session.refresh(merged)
        return merged


class PostgresLedgerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def try_insert(self, entry: CommissionLedgerEntry) -> bool:
        stmt = (
            insert(CommissionLedgerEntry)
            .values(
                tenant_id=entry.tenant_id,
                payout_period=entry.payout_period,
                attendant_id=entry.attendant_id,
                sale_id=entry.sale_id,
                payment_id=entry.payment_id,
                sale_amount_minor_units=entry.sale_amount_minor_units,
                rate_bps=entry.rate_bps,
                commission_minor_units=entry.commission_minor_units,
                created_at=entry.created_at,
            )
            .on_conflict_do_nothing(constraint="uq_commission_ledger_sale_period")
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return (result.rowcount or 0) > 0

    async def list_for_period(self, payout_period: date) -> list[CommissionLedgerEntry]:
        result = await self._session.execute(
            select(CommissionLedgerEntry).where(
                CommissionLedgerEntry.payout_period == payout_period
            )
        )
        return list(result.scalars().all())

    async def sum_for_attendant(
        self, tenant_id: str, payout_period: date, attendant_id: str
    ) -> int:
        result = await self._session.execute(
            select(func.coalesce(func.sum(CommissionLedgerEntry.commission_minor_units), 0)).where(
                and_(
                    CommissionLedgerEntry.tenant_id == tenant_id,
                    CommissionLedgerEntry.payout_period == payout_period,
                    CommissionLedgerEntry.attendant_id == attendant_id,
                )
            )
        )
        return int(result.scalar_one())


class PostgresPayoutIntentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, tenant_id: str, payout_period: date, attendant_id: str
    ) -> PayoutIntent | None:
        result = await self._session.execute(
            select(PayoutIntent).where(
                and_(
                    PayoutIntent.tenant_id == tenant_id,
                    PayoutIntent.payout_period == payout_period,
                    PayoutIntent.attendant_id == attendant_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def upsert(self, intent: PayoutIntent) -> PayoutIntent:
        existing = await self.get(intent.tenant_id, intent.payout_period, intent.attendant_id)
        if existing is not None and existing.state == PayoutIntentState.COMPLETED.value:
            return existing
        if existing is not None:
            if existing.state == PayoutIntentState.SUBMITTED.value and intent.state == (
                PayoutIntentState.PENDING.value
            ):
                return existing
            existing.phone_number = intent.phone_number
            existing.amount_minor_units = intent.amount_minor_units
            existing.state = intent.state
            existing.payments_payout_id = intent.payments_payout_id or existing.payments_payout_id
            existing.failure_reason = intent.failure_reason
            existing.updated_at = intent.updated_at
            await self._session.commit()
            await self._session.refresh(existing)
            return existing
        self._session.add(intent)
        await self._session.commit()
        saved = await self.get(intent.tenant_id, intent.payout_period, intent.attendant_id)
        if saved is None:
            raise RuntimeError(
                f"payout intent missing after insert "
                f"{intent.tenant_id}/{intent.payout_period}/{intent.attendant_id}"
            )
        return saved

    async def list_pending(self, payout_period: date) -> list[PayoutIntent]:
        result = await self._session.execute(
            select(PayoutIntent).where(
                and_(
                    PayoutIntent.payout_period == payout_period,
                    PayoutIntent.state.in_(
                        [PayoutIntentState.PENDING.value, PayoutIntentState.FAILED.value]
                    ),
                )
            )
        )
        return list(result.scalars().all())

    async def list_for_period(self, payout_period: date) -> list[PayoutIntent]:
        result = await self._session.execute(
            select(PayoutIntent).where(PayoutIntent.payout_period == payout_period)
        )
        return list(result.scalars().all())

    async def list_for_tenant(
        self,
        tenant_id: str,
        *,
        attendant_id: str | None = None,
        state: str | None = None,
    ) -> list[PayoutIntent]:
        clauses = [PayoutIntent.tenant_id == tenant_id]
        if attendant_id is not None:
            clauses.append(PayoutIntent.attendant_id == attendant_id)
        if state is not None:
            clauses.append(PayoutIntent.state == state)
        result = await self._session.execute(
            select(PayoutIntent)
            .where(and_(*clauses))
            .order_by(PayoutIntent.payout_period.desc(), PayoutIntent.updated_at.desc())
        )
        return list(result.scalars().all())


async def _set_pos_tenant(session: AsyncSession, tenant_id: str) -> None:
    """POS views sit behind tenant RLS (app.current_tenant_id)."""
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )


class PostgresPaidSalesReader(PaidSalesReader):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_paid_in_period(self, payout_period: date) -> list[PaidSaleRow]:
        # Payments view has no tenant RLS; POS views do — set tenant per batch.
        tenants_result = await self._session.execute(
            text(
                """
                SELECT DISTINCT tenant_id::text AS tenant_id
                FROM payments.v_paid_sales_for_commission
                WHERE (settled_at AT TIME ZONE 'Africa/Nairobi')::date = :period
                """
            ),
            {"period": payout_period},
        )
        tenant_ids = [str(row["tenant_id"]) for row in tenants_result.mappings()]

        sql = text(
            """
            SELECT
              p.tenant_id::text AS tenant_id,
              p.sale_id,
              p.payment_id,
              p.amount_minor_units,
              p.settled_at,
              s.attendant_id::text AS attendant_id,
              s.total_minor AS pos_total_minor
            FROM payments.v_paid_sales_for_commission p
            INNER JOIN pos.v_sales_for_commission s
              ON s.sale_id = p.sale_id
             AND s.tenant_id::text = p.tenant_id::text
            WHERE (p.settled_at AT TIME ZONE 'Africa/Nairobi')::date = :period
              AND p.tenant_id::text = :tenant_id
            """
        )
        rows: list[PaidSaleRow] = []
        for tenant_id in tenant_ids:
            await _set_pos_tenant(self._session, tenant_id)
            result = await self._session.execute(
                sql, {"period": payout_period, "tenant_id": tenant_id}
            )
            for row in result.mappings():
                rows.append(
                    PaidSaleRow(
                        tenant_id=str(row["tenant_id"]),
                        sale_id=row["sale_id"],
                        payment_id=row["payment_id"],
                        amount_minor_units=int(row["amount_minor_units"]),
                        settled_at=row["settled_at"],
                        attendant_id=str(row["attendant_id"]),
                        pos_total_minor=(
                            int(row["pos_total_minor"])
                            if row["pos_total_minor"] is not None
                            else None
                        ),
                    )
                )
        return rows


class PostgresRateReader(RateReader):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def rate_as_of(
        self, tenant_id: str, attendant_id: str, as_of: datetime
    ) -> AttendantRate | None:
        await _set_pos_tenant(self._session, tenant_id)
        sql = text(
            """
            SELECT tenant_id::text, attendant_id::text, rate_bps, effective_from
            FROM pos.v_commission_rates_current
            WHERE tenant_id::text = :tenant_id
              AND attendant_id::text = :attendant_id
              AND effective_from <= :as_of
            ORDER BY effective_from DESC
            LIMIT 1
            """
        )
        result = await self._session.execute(
            sql,
            {"tenant_id": tenant_id, "attendant_id": attendant_id, "as_of": as_of},
        )
        row = result.mappings().first()
        if row is None:
            return None
        return AttendantRate(
            tenant_id=str(row["tenant_id"]),
            attendant_id=str(row["attendant_id"]),
            rate_bps=int(row["rate_bps"]),
            effective_from=row["effective_from"],
        )


class PostgresAttendantReader(AttendantReader):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tenant_id: str, attendant_id: str) -> AttendantContact | None:
        await _set_pos_tenant(self._session, tenant_id)
        sql = text(
            """
            SELECT tenant_id::text, attendant_id::text, phone AS phone_number
            FROM pos.v_attendants_for_payout
            WHERE tenant_id::text = :tenant_id
              AND attendant_id::text = :attendant_id
            """
        )
        result = await self._session.execute(
            sql, {"tenant_id": tenant_id, "attendant_id": attendant_id}
        )
        row = result.mappings().first()
        if row is None:
            return None
        return AttendantContact(
            tenant_id=str(row["tenant_id"]),
            attendant_id=str(row["attendant_id"]),
            phone_number=str(row["phone_number"]),
        )
