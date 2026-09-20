from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from commission.db import Base
from commission.domain.state import CloseRunStatus, PayoutIntentState

SCHEMA = "commission"


class CloseRun(Base):
    """One daily-close execution per payout period."""

    __tablename__ = "close_runs"
    __table_args__ = (
        UniqueConstraint("payout_period", name="uq_close_runs_period"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payout_period: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CloseRunStatus.RUNNING.value
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class CommissionLedgerEntry(Base):
    """Append-only owed commission per sale for a period ([ADR-004])."""

    __tablename__ = "commission_ledger"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "payout_period",
            "attendant_id",
            "sale_id",
            name="uq_commission_ledger_sale_period",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payout_period: Mapped[date] = mapped_column(Date, nullable=False)
    attendant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sale_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    sale_amount_minor_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rate_bps: Mapped[int] = mapped_column(nullable=False)
    commission_minor_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PayoutIntent(Base):
    """Per-attendant payout for a period — drives B2C via Payments."""

    __tablename__ = "payout_intents"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "payout_period",
            "attendant_id",
            name="uq_payout_intents_tenant_period_attendant",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payout_period: Mapped[date] = mapped_column(Date, nullable=False)
    attendant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_minor_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PayoutIntentState.PENDING.value
    )
    payments_payout_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @property
    def intent_state(self) -> PayoutIntentState:
        return PayoutIntentState(self.state)
