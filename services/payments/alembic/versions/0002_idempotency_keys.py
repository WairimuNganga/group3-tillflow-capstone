"""Create idempotency_keys table.

Revision ID: 0002_idempotency_keys
Revises: 0001_create_payments_schema
Create Date: 2026-09-14

Tenant-scoped idempotency records for money-path endpoints ([ADR-004], threat model M1).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_idempotency_keys"
down_revision: str | Sequence[str] | None = "0001_create_payments_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("service", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "service", "tenant_id", "key", name="uq_idempotency_service_tenant_key"
        ),
        schema="payments",
    )
    op.create_index(
        "ix_idempotency_keys_expires_at",
        "idempotency_keys",
        ["expires_at"],
        schema="payments",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_idempotency_keys_expires_at", table_name="idempotency_keys", schema="payments"
    )
    op.drop_table("idempotency_keys", schema="payments")
