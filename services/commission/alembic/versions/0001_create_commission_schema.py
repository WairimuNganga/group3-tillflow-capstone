"""Create commission schema.

Revision ID: 0001_create_commission_schema
Revises:
Create Date: 2026-09-20

Intentionally a no-op. The ``commission`` schema is created, owned and dropped
exclusively by db-bootstrap; Alembic never touches it.

Migrations run as the RDS master but ``SET ROLE tillflow_commission_owner``
immediately (see ``alembic/env.py``), so every object they create is owned by
the owner role and inherits its RLS and default-privilege grants (ADR-005).
That owner role holds ownership of its schema and nothing more -- it has no
``CREATE`` on the database, by design. A ``CREATE SCHEMA`` here therefore fails
with ``InsufficientPrivilege``, and ``IF NOT EXISTS`` does not help: Postgres
checks the database ``CREATE`` privilege before it checks existence, so it
raises even when db-bootstrap has already created the schema.

Do not reintroduce schema DDL here. Granting the owner role database-level
``CREATE`` to make it work would undo the least-privilege split this revision
exists to respect. Locally the schema comes from the pre-``SET ROLE``
convenience statement in ``env.py``, which runs as the connecting role.
"""

from collections.abc import Sequence

revision: str = "0001_create_commission_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: db-bootstrap owns schema creation."""


def downgrade() -> None:
    """No-op: db-bootstrap owns schema deletion."""
