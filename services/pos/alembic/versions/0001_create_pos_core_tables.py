"""Create POS core tables with tenant-scoped constraints and RLS.

Revision ID: 0001_create_pos_core_tables
Revises:
Create Date: 2026-09-16

Runs as tillflow_pos_owner (set in alembic/env.py), so objects are owner-owned —
default-privilege grants reach tillflow_pos and RLS applies. The pos schema and
role pair are created by the G2 DB bootstrap (AWS) or local/init-db.sql (dev),
not here (ADR-002 / ADR-005 / G2 handover).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_create_pos_core_tables"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "pos"
_UUID = postgresql.UUID(as_uuid=True)
_NOW = sa.text("now()")
_GEN_UUID = sa.text("gen_random_uuid()")

_TENANT_TABLES = ("tenants", "users", "tills", "commission_rates", "sales", "sale_items")


def upgrade() -> None:
    op.execute("CREATE OR REPLACE FUNCTION pos.set_updated_at() RETURNS trigger AS $$ "
               "BEGIN NEW.updated_at = now(); RETURN NEW; END; $$ LANGUAGE plpgsql")

    op.create_table(
        "tenants",
        sa.Column("id", _UUID, server_default=_GEN_UUID, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status in ('active','suspended')", name="tenants_status_check"),
        schema=SCHEMA,
    )

    op.create_table(
        "users",
        sa.Column("id", _UUID, server_default=_GEN_UUID, nullable=False),
        sa.Column("tenant_id", _UUID, nullable=False),
        sa.Column("phone", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], [f"{SCHEMA}.tenants.id"]),
        sa.UniqueConstraint("tenant_id", "id", name="uq_users_tenant_id"),
        sa.UniqueConstraint("tenant_id", "phone", name="uq_users_tenant_phone"),
        sa.CheckConstraint("role in ('owner','attendant')", name="users_role_check"),
        sa.CheckConstraint("status in ('active','disabled')", name="users_status_check"),
        schema=SCHEMA,
    )

    op.create_table(
        "tills",
        sa.Column("id", _UUID, server_default=_GEN_UUID, nullable=False),
        sa.Column("tenant_id", _UUID, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("shortcode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], [f"{SCHEMA}.tenants.id"]),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tills_tenant_id"),
        sa.UniqueConstraint("tenant_id", "shortcode", name="uq_tills_tenant_shortcode"),
        sa.CheckConstraint("status in ('active','disabled')", name="tills_status_check"),
        schema=SCHEMA,
    )

    op.create_table(
        "commission_rates",
        sa.Column("id", _UUID, server_default=_GEN_UUID, nullable=False),
        sa.Column("tenant_id", _UUID, nullable=False),
        sa.Column("attendant_id", _UUID, nullable=False),
        sa.Column("rate_bps", sa.Integer(), nullable=False),
        sa.Column(
            "effective_from", sa.DateTime(timezone=True), server_default=_NOW, nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], [f"{SCHEMA}.tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "attendant_id"], [f"{SCHEMA}.users.tenant_id", f"{SCHEMA}.users.id"]
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_commission_rates_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "attendant_id", "effective_from", name="uq_commission_rates_effective"
        ),
        sa.CheckConstraint("rate_bps between 0 and 10000", name="commission_rate_bps_range"),
        schema=SCHEMA,
    )

    op.create_table(
        "sales",
        sa.Column("id", _UUID, server_default=_GEN_UUID, nullable=False),
        sa.Column("tenant_id", _UUID, nullable=False),
        sa.Column("till_id", _UUID, nullable=False),
        sa.Column("attendant_id", _UUID, nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="KES", nullable=False),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        sa.Column("customer_msisdn", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], [f"{SCHEMA}.tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "till_id"], [f"{SCHEMA}.tills.tenant_id", f"{SCHEMA}.tills.id"]
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "attendant_id"], [f"{SCHEMA}.users.tenant_id", f"{SCHEMA}.users.id"]
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_sales_tenant_id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_sales_tenant_idempotency"),
        sa.CheckConstraint(
            "status in ('pending','awaiting_payment','paid','failed','cancelled')",
            name="sales_status_check",
        ),
        sa.CheckConstraint("total_minor >= 0", name="sales_total_nonneg"),
        schema=SCHEMA,
    )
    op.create_index("ix_sales_tenant_status", "sales", ["tenant_id", "status"], schema=SCHEMA)
    op.create_index("ix_sales_tenant_created", "sales", ["tenant_id", "created_at"], schema=SCHEMA)

    op.create_table(
        "sale_items",
        sa.Column("id", _UUID, server_default=_GEN_UUID, nullable=False),
        sa.Column("tenant_id", _UUID, nullable=False),
        sa.Column("sale_id", _UUID, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("line_total_minor", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sale_id"],
            [f"{SCHEMA}.sales.tenant_id", f"{SCHEMA}.sales.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("quantity > 0", name="sale_items_qty_pos"),
        sa.CheckConstraint("unit_price_minor >= 0", name="sale_items_price_nonneg"),
        sa.CheckConstraint("line_total_minor >= 0", name="sale_items_line_nonneg"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_sale_items_tenant_sale", "sale_items", ["tenant_id", "sale_id"], schema=SCHEMA
    )

    for table in ("tenants", "users", "tills", "sales"):
        op.execute(
            f"CREATE TRIGGER {table}_updated_at BEFORE UPDATE ON pos.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION pos.set_updated_at()"
        )

    # RLS: ENABLE + FORCE on every tenant-owned table (ADR-005). FORCE is
    # required because tillflow_pos_owner is NOBYPASSRLS and owns these tables.
    for table in _TENANT_TABLES:
        op.execute(f"ALTER TABLE pos.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE pos.{table} FORCE ROW LEVEL SECURITY")

    # tenants filters on its own id; every other table on tenant_id. Unset GUC
    # (missing_ok=true) -> NULL -> zero rows, never an error.
    op.execute(
        "CREATE POLICY tenant_isolation ON pos.tenants "
        "USING (id = current_setting('app.current_tenant_id', true)::uuid) "
        "WITH CHECK (id = current_setting('app.current_tenant_id', true)::uuid)"
    )
    for table in ("users", "tills", "commission_rates", "sales", "sale_items"):
        op.execute(
            f"CREATE POLICY tenant_isolation ON pos.{table} "
            "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid) "
            "WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
        )


def downgrade() -> None:
    for table in _TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON pos.{table}")
    op.drop_table("sale_items", schema=SCHEMA)
    op.drop_table("sales", schema=SCHEMA)
    op.drop_table("commission_rates", schema=SCHEMA)
    op.drop_table("tills", schema=SCHEMA)
    op.drop_table("users", schema=SCHEMA)
    op.drop_table("tenants", schema=SCHEMA)
    op.execute("DROP FUNCTION IF EXISTS pos.set_updated_at()")
