"""Create payments schema.

Revision ID: 0001_create_payments_schema
Revises:
Create Date: 2026-09-14

Tables land in Phase 2; this migration only establishes the schema and Alembic
version table location per ADR-002.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0001_create_payments_schema"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS payments")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS payments CASCADE")
