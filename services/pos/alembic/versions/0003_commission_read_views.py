"""Create POS read-only views for the commission worker.

Revision ID: 0003_commission_read_views
Revises: 0002_sale_payment_reference
Create Date: 2026-09-20

ADR-002: commission never gets raw table grants — only these views.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_commission_read_views"
down_revision: str | Sequence[str] | None = "0002_sale_payment_reference"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW pos.v_sales_for_commission AS
        SELECT
          id AS sale_id,
          tenant_id,
          attendant_id,
          total_minor,
          payment_id,
          paid_at
        FROM pos.sales
        WHERE status = 'paid'
          AND paid_at IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW pos.v_commission_rates_current AS
        SELECT
          tenant_id,
          attendant_id,
          rate_bps,
          effective_from
        FROM pos.commission_rates
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW pos.v_attendants_for_payout AS
        SELECT
          id AS attendant_id,
          tenant_id,
          phone
        FROM pos.users
        WHERE role = 'attendant'
          AND status = 'active'
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tillflow_commission') THEN
            GRANT SELECT ON pos.v_sales_for_commission TO tillflow_commission;
            GRANT SELECT ON pos.v_commission_rates_current TO tillflow_commission;
            GRANT SELECT ON pos.v_attendants_for_payout TO tillflow_commission;
          END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS pos.v_attendants_for_payout")
    op.execute("DROP VIEW IF EXISTS pos.v_commission_rates_current")
    op.execute("DROP VIEW IF EXISTS pos.v_sales_for_commission")
