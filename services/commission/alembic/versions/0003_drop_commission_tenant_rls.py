"""Drop tenant RLS from commission ledger/intents.

Revision ID: 0003_drop_commission_tenant_rls
Revises: 0002_commission_core_tables
Create Date: 2026-09-20

Close runs across all tenants in one job; session GUC tenant RLS hid
ledger/intents from payout and summary after the writer set_config expired.
Tenant scoping stays in application queries (tenant_id column filters).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_drop_commission_tenant_rls"
down_revision: str | Sequence[str] | None = "0002_commission_core_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "commission"


def upgrade() -> None:
    for table in ("commission_ledger", "payout_intents"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {SCHEMA}.{table}")
        op.execute(f"ALTER TABLE {SCHEMA}.{table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {SCHEMA}.{table} DISABLE ROW LEVEL SECURITY")


def downgrade() -> None:
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
