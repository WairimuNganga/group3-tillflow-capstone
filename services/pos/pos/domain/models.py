"""ORM models for the ``pos`` schema.

These are the SQLAlchemy models registered on ``pos.db.Base`` (Alembic reads
``Base.metadata`` for autogenerate). The migration in ``alembic/versions`` is the
source of truth for DDL that ORM metadata can't express — RLS, FORCE, and the
composite tenant-scoped foreign keys.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pos.db import Base
from pos.domain.state import SaleStatus

SCHEMA = "pos"


class Tenant(Base):
    """The merchant. Its own ``id`` is the tenant key (RLS filters on ``id``)."""

    __tablename__ = "tenants"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    """A tenant's owner or attendant. ``phone`` is PII (threat model)."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "phone"),
        CheckConstraint("role in ('owner','attendant')", name="users_role_check"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Till(Base):
    """A tenant's M-Pesa till / shortcode."""

    __tablename__ = "tills"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "shortcode"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    shortcode: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CommissionRate(Base):
    """Per-attendant commission rate the owner sets at tenant setup.

    ``rate_bps`` is integer basis points (0..10000) — money math stays exact.
    """

    __tablename__ = "commission_rates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "attendant_id", "effective_from"),
        ForeignKeyConstraint(
            ["tenant_id", "attendant_id"], [f"{SCHEMA}.users.tenant_id", f"{SCHEMA}.users.id"]
        ),
        CheckConstraint("rate_bps between 0 and 10000", name="commission_rate_bps_range"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attendant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Sale(Base):
    """The sale aggregate root and its state machine. Money is minor units."""

    __tablename__ = "sales"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_sales_tenant_idempotency"),
        ForeignKeyConstraint(
            ["tenant_id", "till_id"], [f"{SCHEMA}.tills.tenant_id", f"{SCHEMA}.tills.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "attendant_id"], [f"{SCHEMA}.users.tenant_id", f"{SCHEMA}.users.id"]
        ),
        CheckConstraint("total_minor >= 0", name="sales_total_nonneg"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    till_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attendant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=SaleStatus.PENDING.value)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KES")
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    customer_msisdn: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set when Payments reports the outcome: which payment settled this sale and
    # the M-Pesa receipt behind it, so every paid sale traces back to real money.
    payment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    mpesa_receipt: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    items: Mapped[list[SaleItem]] = relationship(
        back_populates="sale", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def sale_status(self) -> SaleStatus:
        return SaleStatus(self.status)


class SaleItem(Base):
    """A sale line item. Composite FK ties it to a sale of the same tenant."""

    __tablename__ = "sale_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "sale_id"],
            [f"{SCHEMA}.sales.tenant_id", f"{SCHEMA}.sales.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("quantity > 0", name="sale_items_qty_pos"),
        CheckConstraint("unit_price_minor >= 0", name="sale_items_price_nonneg"),
        CheckConstraint("line_total_minor >= 0", name="sale_items_line_nonneg"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sale_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    line_total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sale: Mapped[Sale] = relationship(back_populates="items")
