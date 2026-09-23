"""Grant commission cross-schema read access to the payments view.

Revision ID: 0005_grant_commission_read_view
Revises: 0004_paid_sales_commission_view
Create Date: 2026-09-24

0004 granted SELECT on payments.v_paid_sales_for_commission but never granted
USAGE on the payments schema itself. In PostgreSQL a table grant is unusable
without schema USAGE, so the daily close failed in AWS with:

    permission denied for schema payments
    SELECT DISTINCT tenant_id::text FROM payments.v_paid_sales_for_commission

db-bootstrap grants each service USAGE on its OWN schema only
(`GRANT USAGE ON SCHEMA payments TO tillflow_payments`), deliberately -- it
does not know which cross-schema reads are legitimate. The owning schema's
migration is the right place to express "commission may read this one view",
because the payments owner role owns both the schema and the view and is the
only role entitled to grant on them.

A new revision rather than an edit to 0004: 0004 has already run in dev, so
editing it would change nothing on a deployed database.

Scope is deliberately narrow -- USAGE on the schema plus SELECT on one view.
Commission gets no access to payments.payments (ADR-002: it reads the view,
never the raw table).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_grant_commission_read_view"
down_revision: str | Sequence[str] | None = "0004_paid_sales_commission_view"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The role is created by db-bootstrap, which does not run against a local
# throwaway database or in CI. Guarding on existence keeps this migration
# runnable everywhere; GRANT itself is idempotent, so re-running is safe.
_GRANT = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tillflow_commission') THEN
    GRANT USAGE ON SCHEMA payments TO tillflow_commission;
    GRANT SELECT ON payments.v_paid_sales_for_commission TO tillflow_commission;
  END IF;
END
$$
"""

_REVOKE = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tillflow_commission') THEN
    REVOKE SELECT ON payments.v_paid_sales_for_commission FROM tillflow_commission;
    REVOKE USAGE ON SCHEMA payments FROM tillflow_commission;
  END IF;
END
$$
"""


def upgrade() -> None:
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute(_REVOKE)
