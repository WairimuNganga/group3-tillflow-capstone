"""Create payments schema.

Revision ID: 0001_create_payments_schema
Revises:
Create Date: 2026-09-14

Intentionally a no-op. The ``payments`` schema is created, owned and dropped
exclusively by db-bootstrap; Alembic never touches it.

Migrations run as the RDS master but ``SET ROLE tillflow_payments_owner``
immediately (see ``alembic/env.py``), so every object they create is owned by
the owner role and inherits its RLS and default-privilege grants (ADR-005).
That owner role holds ownership of its schema and nothing more -- it has no
``CREATE`` on the database, by design. A ``CREATE SCHEMA`` here therefore fails
with ``InsufficientPrivilege``, and ``IF NOT EXISTS`` does not help: Postgres
checks the database ``CREATE`` privilege before it checks existence, so it
raises even when db-bootstrap has already created the schema.

Do not reintroduce schema DDL here. Granting the owner role database-level
``CREATE`` to make it work would undo the least-privilege split this revision
exists to respect. Locally the schema comes from ``local/init-db.sql``.

Tables land in Phase 2; the Alembic version table lives in the payments schema
per ADR-002 (``version_table_schema`` in ``env.py``).
"""

from collections.abc import Sequence

revision: str = "0001_create_payments_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: db-bootstrap owns schema creation."""


def downgrade() -> None:
    """No-op: db-bootstrap owns schema deletion."""
