"""Create commission schema.

Revision ID: 0001_create_commission_schema
Revises:
Create Date: 2026-09-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_create_commission_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS commission")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS commission CASCADE")
