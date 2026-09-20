"""Read models for cross-schema commission eligibility (payments + POS views)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PaidSaleRow:
    """Row from payments.v_paid_sales_for_commission ∩ POS attribution."""

    tenant_id: str
    sale_id: UUID
    payment_id: UUID | None
    amount_minor_units: int
    settled_at: datetime
    attendant_id: str
    pos_total_minor: int | None = None


@dataclass(frozen=True, slots=True)
class AttendantRate:
    tenant_id: str
    attendant_id: str
    rate_bps: int
    effective_from: datetime


@dataclass(frozen=True, slots=True)
class AttendantContact:
    tenant_id: str
    attendant_id: str
    phone_number: str


class PaidSalesReader:
    async def list_paid_in_period(self, payout_period: date) -> list[PaidSaleRow]:
        raise NotImplementedError


class RateReader:
    async def rate_as_of(
        self, tenant_id: str, attendant_id: str, as_of: datetime
    ) -> AttendantRate | None:
        raise NotImplementedError


class AttendantReader:
    async def get(self, tenant_id: str, attendant_id: str) -> AttendantContact | None:
        raise NotImplementedError
