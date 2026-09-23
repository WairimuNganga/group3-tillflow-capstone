"""Alembic revisions must never manage the payments schema itself.

Migrations ``SET ROLE tillflow_payments_owner`` (alembic/env.py) so created
objects are owned by the owner role. That role deliberately has no ``CREATE``
on the database, so any schema DDL in a revision fails with
``InsufficientPrivilege`` -- and ``IF NOT EXISTS`` does not save it, because
Postgres checks the privilege before the existence test. Schema creation,
ownership and deletion belong to db-bootstrap.

This is a regression guard: the CodeBuild MigrateDb action failed exactly this
way on 2026-09-20 (see evidence/delivery/migration-failure-20260920.md).
"""

import re
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

# Matches CREATE/DROP SCHEMA with any amount of whitespace between the words,
# so a reformatted or line-wrapped statement cannot slip past.
SCHEMA_DDL = re.compile(r"\b(CREATE|DROP)\s+SCHEMA\b", re.IGNORECASE)

# A docstring may *name* the forbidden statement while explaining why it is
# forbidden; only executable lines are checked.
DOCSTRING_DELIM = re.compile(r'"""|\'\'\'')


def _revisions() -> list[Path]:
    return sorted(p for p in VERSIONS.glob("*.py") if p.name != "__init__.py")


def _code_lines(source: str) -> list[str]:
    """Source lines with docstrings and ``#`` comments stripped."""
    lines, in_docstring = [], False
    for raw in source.splitlines():
        line = raw.split("#", 1)[0]
        delims = len(DOCSTRING_DELIM.findall(line))
        if in_docstring:
            if delims:
                in_docstring = False
                line = line.split('"""')[-1].split("'''")[-1]
            else:
                continue
        elif delims == 1:
            in_docstring = True
            line = DOCSTRING_DELIM.split(line, 1)[0]
        lines.append(line)
    return lines


def test_there_are_revisions_to_check():
    # Guards against the whole suite passing vacuously if the glob breaks.
    names = [p.name for p in _revisions()]
    assert "0001_create_payments_schema.py" in names


@pytest.mark.parametrize("revision", _revisions(), ids=lambda p: p.name)
def test_revision_contains_no_schema_ddl(revision: Path):
    offenders = [
        line.strip()
        for line in _code_lines(revision.read_text())
        if SCHEMA_DDL.search(line)
    ]
    assert not offenders, (
        f"{revision.name} executes schema DDL: {offenders}. "
        "db-bootstrap owns the payments schema; the owner role the migration "
        "SET ROLEs into has no CREATE on the database."
    )


def test_0001_upgrade_and_downgrade_are_no_ops():
    source = (VERSIONS / "0001_create_payments_schema.py").read_text()
    body = _code_lines(source)

    # No calls of any kind in the revision body -- not just no schema DDL.
    assert not [line for line in body if "op." in line], (
        "0001 must stay a no-op: the payments schema is created and dropped by "
        "db-bootstrap only."
    )
    assert "def upgrade() -> None:" in source
    assert "def downgrade() -> None:" in source


# --- Cross-schema grant for commission --------------------------------------
#
# A SELECT grant on a view is unusable without USAGE on its schema. 0004
# granted only SELECT, so the AWS daily close failed with "permission denied
# for schema payments". 0005 adds the missing USAGE. db-bootstrap deliberately
# grants each service USAGE on its own schema only, so this grant has to live
# in the owning schema's migration.

GRANT_REVISION = VERSIONS / "0005_grant_commission_read_view.py"


def test_commission_grant_migration_exists():
    assert GRANT_REVISION.exists(), (
        "payments must ship a migration granting commission cross-schema read "
        "access; without it the daily close returns 500."
    )


def test_grant_covers_schema_usage_and_view_select():
    sql = GRANT_REVISION.read_text()

    # Both halves, or the grant does nothing usable.
    assert re.search(r"GRANT\s+USAGE\s+ON\s+SCHEMA\s+payments\s+TO\s+tillflow_commission", sql)
    assert re.search(
        r"GRANT\s+SELECT\s+ON\s+payments\.v_paid_sales_for_commission\s+TO\s+tillflow_commission",
        sql,
    )


def test_grant_is_guarded_on_role_existence():
    """db-bootstrap creates tillflow_commission; local and CI databases do not."""
    sql = GRANT_REVISION.read_text()
    assert "pg_roles" in sql and "tillflow_commission" in sql


def test_commission_is_not_granted_the_raw_payments_table():
    """ADR-002: commission reads the view, never payments.payments."""
    sql = GRANT_REVISION.read_text()
    granted = re.findall(r"GRANT\s+SELECT\s+ON\s+([a-z_.]+)\s+TO\s+tillflow_commission", sql)
    assert granted == ["payments.v_paid_sales_for_commission"], (
        f"commission must only be granted the view, got: {granted}"
    )


def test_grant_migration_is_reversible():
    sql = GRANT_REVISION.read_text()
    assert "REVOKE USAGE ON SCHEMA payments FROM tillflow_commission" in sql
