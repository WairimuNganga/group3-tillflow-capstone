"""Create payments.v_paid_sales_for_commission read-only view.

Revision ID: 0004_paid_sales_commission_view
Revises: 0003_payment_core_tables
Create Date: 2026-09-20

Commission reads this view only — never raw payments.payments (ADR-002).
Platform grants SELECT to tillflow_commission after apply.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_paid_sales_commission_view"
down_revision: str | Sequence[str] | None = "0003_payment_core_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW payments.v_paid_sales_for_commission AS
        SELECT
          id AS payment_id,
          tenant_id,
          sale_id,
          amount_minor_units,
          amount_whole_kes,
          state,
          settled_at,
          mpesa_receipt_number,
          created_at,
          updated_at
        FROM payments.payments
        WHERE state = 'paid'
          AND settled_at IS NOT NULL
        """
    )
    # Best-effort grant when role exists (AWS bootstrap); ignore locally if absent.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tillflow_commission') THEN
            GRANT SELECT ON payments.v_paid_sales_for_commission TO tillflow_commission;
          END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS payments.v_paid_sales_for_commission")
