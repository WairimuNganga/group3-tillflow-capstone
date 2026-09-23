"""Grant commission cross-schema read access to the POS commission views.

Revision ID: 0004_grant_commission_schema_usage
Revises: 0003_commission_read_views
Create Date: 2026-09-24

The same defect as payments 0005, found while fixing it. 0003 granted SELECT
on the three commission views but never granted USAGE on the pos schema, and a
table grant without schema USAGE is unusable:

    permission denied for schema pos

This had not surfaced yet only because the daily close reads
payments.v_paid_sales_for_commission first and failed there. Fixing payments
alone would have moved the same 500 to the next query.

db-bootstrap grants each service USAGE on its OWN schema only; the owning
schema's migration is where a legitimate cross-schema read is declared, since
the pos owner role owns both the schema and the views.

Scope is the three views commission already reads -- no access to pos.sales or
any other table.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_grant_commission_schema_usage"
down_revision: str | Sequence[str] | None = "0003_commission_read_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Guarded on role existence: db-bootstrap creates tillflow_commission in AWS,
# but it does not run locally or in CI. GRANT is idempotent.
_GRANT = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tillflow_commission') THEN
    GRANT USAGE ON SCHEMA pos TO tillflow_commission;
    GRANT SELECT ON pos.v_sales_for_commission TO tillflow_commission;
    GRANT SELECT ON pos.v_commission_rates_current TO tillflow_commission;
    GRANT SELECT ON pos.v_attendants_for_payout TO tillflow_commission;
  END IF;
END
$$
"""

_REVOKE = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tillflow_commission') THEN
    REVOKE SELECT ON pos.v_attendants_for_payout FROM tillflow_commission;
    REVOKE SELECT ON pos.v_commission_rates_current FROM tillflow_commission;
    REVOKE SELECT ON pos.v_sales_for_commission FROM tillflow_commission;
    REVOKE USAGE ON SCHEMA pos FROM tillflow_commission;
  END IF;
END
$$
"""


def upgrade() -> None:
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute(_REVOKE)
