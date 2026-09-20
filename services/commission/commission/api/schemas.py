from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class CloseRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    payout_period: date = Field(
        description="EAT (GMT+3) calendar date of the close period"
    )


class CloseResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    payout_period: date
    status: str
    ledger_lines_written: int
    intents_enqueued: int
    skipped_mismatch: int
    already_completed: bool = False


class AttendantPayoutRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    payout_period: date
    attendant_id: str


class AttendantPayoutResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    payout_period: date
    attendant_id: str
    state: str
    amount_minor_units: int
    payments_payout_id: str | None = None
    # True when this call did not start a new B2C (idempotent replay).
    already_requested: bool = False
    next_payout_period: date | None = None


class LedgerLineSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    sale_id: str
    attendant_id: str
    sale_amount_minor_units: int
    rate_bps: int
    commission_minor_units: int


class PayoutIntentSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    attendant_id: str
    state: str
    amount_minor_units: int
    payments_payout_id: str | None = None


class PayoutListItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    payout_period: date
    attendant_id: str
    phone_number: str
    amount_minor_units: int
    state: str
    payments_payout_id: str | None = None
    failure_reason: str | None = None
    created_at: str
    updated_at: str


class PayoutListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    payouts: list[PayoutListItem]


class PeriodSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    payout_period: date
    tenant_id: str
    close_status: str | None
    ledger_lines: list[LedgerLineSummary]
    ledger_commission_minor_units: int
    payout_intents: list[PayoutIntentSummary]
