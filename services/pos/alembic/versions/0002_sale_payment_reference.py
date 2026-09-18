"""Record which payment settled a sale (payment_id, M-Pesa receipt, paid_at).

Revision ID: 0002_sale_payment_reference
Revises: 0001_create_pos_core_tables
Create Date: 2026-09-18

Payments reports the outcome to POS; storing the payment id and receipt makes
every `paid` sale traceable to real money, and gives Commission an auditable
basis for payouts ([ADR-004]).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_sale_payment_reference"
down_revision: str | Sequence[str] | None = "0001_create_pos_core_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "pos"


def upgrade() -> None:
    op.add_column(
        "sales",
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column("sales", sa.Column("mpesa_receipt", sa.Text(), nullable=True), schema=SCHEMA)
    op.add_column(
        "sales",
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    # One sale per payment, per tenant: a replayed payment result can never
    # attach the same payment to a second sale.
    op.create_unique_constraint(
        "uq_sales_tenant_payment", "sales", ["tenant_id", "payment_id"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_constraint("uq_sales_tenant_payment", "sales", schema=SCHEMA, type_="unique")
    op.drop_column("sales", "paid_at", schema=SCHEMA)
    op.drop_column("sales", "mpesa_receipt", schema=SCHEMA)
    op.drop_column("sales", "payment_id", schema=SCHEMA)
