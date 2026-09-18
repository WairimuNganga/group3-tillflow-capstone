"""Create payment, callback, ledger, and payout tables.

Revision ID: 0003_payment_core_tables
Revises: 0002_idempotency_keys
Create Date: 2026-09-14

Core money-path tables for the payments service ([ADR-004]).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_payment_core_tables"
down_revision: str | Sequence[str] | None = "0002_idempotency_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "payments"


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("sale_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("amount_minor_units", sa.BigInteger(), nullable=False),
        sa.Column("amount_whole_kes", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("phone_number", sa.String(length=32), nullable=False),
        sa.Column("merchant_request_id", sa.String(length=64), nullable=True),
        sa.Column("checkout_request_id", sa.String(length=64), nullable=True),
        sa.Column("mpesa_receipt_number", sa.String(length=64), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "sale_id", name="uq_payments_tenant_sale"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_payments_tenant_idempotency"),
        schema=SCHEMA,
    )
    op.create_index("ix_payments_tenant_id", "payments", ["tenant_id"], schema=SCHEMA)
    op.create_index(
        "ix_payments_checkout_request_id", "payments", ["checkout_request_id"], schema=SCHEMA
    )

    op.create_table(
        "payouts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("originator_conversation_id", sa.String(length=128), nullable=False),
        sa.Column("attendant_id", sa.String(length=128), nullable=False),
        sa.Column("phone_number", sa.String(length=32), nullable=False),
        sa.Column("amount_minor_units", sa.BigInteger(), nullable=False),
        sa.Column("amount_whole_kes", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "originator_conversation_id",
            name="uq_payouts_tenant_originator",
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_payouts_tenant_id", "payouts", ["tenant_id"], schema=SCHEMA)

    op.create_table(
        "payment_callbacks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_request_id", sa.String(length=64), nullable=False),
        sa.Column("checkout_request_id", sa.String(length=64), nullable=False),
        sa.Column("result_code", sa.Integer(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["payment_id"], [f"{SCHEMA}.payments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "merchant_request_id",
            "checkout_request_id",
            name="uq_payment_callbacks_provider_ids",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "payment_ledger",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payout_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entry_type", sa.String(length=64), nullable=False),
        sa.Column("amount_minor_units", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["payment_id"], [f"{SCHEMA}.payments.id"]),
        sa.ForeignKeyConstraint(["payout_id"], [f"{SCHEMA}.payouts.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index("ix_payment_ledger_tenant_id", "payment_ledger", ["tenant_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_payment_ledger_tenant_id", table_name="payment_ledger", schema=SCHEMA)
    op.drop_table("payment_ledger", schema=SCHEMA)
    op.drop_table("payment_callbacks", schema=SCHEMA)
    op.drop_index("ix_payouts_tenant_id", table_name="payouts", schema=SCHEMA)
    op.drop_table("payouts", schema=SCHEMA)
    op.drop_index("ix_payments_checkout_request_id", table_name="payments", schema=SCHEMA)
    op.drop_index("ix_payments_tenant_id", table_name="payments", schema=SCHEMA)
    op.drop_table("payments", schema=SCHEMA)
