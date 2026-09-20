"""Create close_runs, commission_ledger, and payout_intents.

Revision ID: 0002_commission_core_tables
Revises: 0001_create_commission_schema
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_commission_core_tables"
down_revision: str | Sequence[str] | None = "0001_create_commission_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "commission"


def upgrade() -> None:
    op.create_table(
        "close_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payout_period", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payout_period", name="uq_close_runs_period"),
        schema=SCHEMA,
    )

    op.create_table(
        "commission_ledger",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("payout_period", sa.Date(), nullable=False),
        sa.Column("attendant_id", sa.String(length=128), nullable=False),
        sa.Column("sale_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sale_amount_minor_units", sa.BigInteger(), nullable=False),
        sa.Column("rate_bps", sa.Integer(), nullable=False),
        sa.Column("commission_minor_units", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "payout_period",
            "attendant_id",
            "sale_id",
            name="uq_commission_ledger_sale_period",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_commission_ledger_tenant_id",
        "commission_ledger",
        ["tenant_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "payout_intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("payout_period", sa.Date(), nullable=False),
        sa.Column("attendant_id", sa.String(length=128), nullable=False),
        sa.Column("phone_number", sa.String(length=32), nullable=False),
        sa.Column("amount_minor_units", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("payments_payout_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "payout_period",
            "attendant_id",
            name="uq_payout_intents_tenant_period_attendant",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_payout_intents_tenant_id",
        "payout_intents",
        ["tenant_id"],
        schema=SCHEMA,
    )

    for table in ("commission_ledger", "payout_intents"):
        op.execute(f"ALTER TABLE {SCHEMA}.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {SCHEMA}.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {SCHEMA}.{table}
              USING (tenant_id = current_setting('app.current_tenant_id', true))
              WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
            """
        )


def downgrade() -> None:
    op.drop_index("ix_payout_intents_tenant_id", table_name="payout_intents", schema=SCHEMA)
    op.drop_table("payout_intents", schema=SCHEMA)
    op.drop_index(
        "ix_commission_ledger_tenant_id", table_name="commission_ledger", schema=SCHEMA
    )
    op.drop_table("commission_ledger", schema=SCHEMA)
    op.drop_table("close_runs", schema=SCHEMA)
