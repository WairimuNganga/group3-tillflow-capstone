from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from payments.db import Base
from payments.domain.state import PaymentState, PayoutState

SCHEMA = "payments"


class Payment(Base):
    """One M-Pesa collection attempt for a POS sale."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sale_id", name="uq_payments_tenant_sale"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_payments_tenant_idempotency"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    sale_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_minor_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_whole_kes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default=PaymentState.PENDING.value)
    phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    merchant_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checkout_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    mpesa_receipt_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    callbacks: Mapped[list[PaymentCallback]] = relationship(back_populates="payment")
    ledger_entries: Mapped[list[PaymentLedgerEntry]] = relationship(back_populates="payment")

    @property
    def payment_state(self) -> PaymentState:
        return PaymentState(self.state)


class Payout(Base):
    """One B2C commission disbursement ([ADR-004])."""

    __tablename__ = "payouts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "originator_conversation_id",
            name="uq_payouts_tenant_originator",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    originator_conversation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    attendant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_minor_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_whole_kes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default=PayoutState.PENDING.value)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    ledger_entries: Mapped[list[PaymentLedgerEntry]] = relationship(back_populates="payout")

    @property
    def payout_state(self) -> PayoutState:
        return PayoutState(self.state)


class PaymentCallback(Base):
    """Raw Daraja STK callback payload — deduped on provider IDs ([ADR-004])."""

    __tablename__ = "payment_callbacks"
    __table_args__ = (
        UniqueConstraint(
            "merchant_request_id",
            "checkout_request_id",
            name="uq_payment_callbacks_provider_ids",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.payments.id"), nullable=False
    )
    merchant_request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    checkout_request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    result_code: Mapped[int | None] = mapped_column(nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    payment: Mapped[Payment] = relationship(back_populates="callbacks")


class PaymentLedgerEntry(Base):
    """Append-only money effects for audit and invariant checks ([ADR-004])."""

    __tablename__ = "payment_ledger"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.payments.id"), nullable=True
    )
    payout_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.payouts.id"), nullable=True
    )
    entry_type: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_minor_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    payment: Mapped[Payment | None] = relationship(back_populates="ledger_entries")
    payout: Mapped[Payout | None] = relationship(back_populates="ledger_entries")
