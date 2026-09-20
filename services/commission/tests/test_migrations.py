"""Alembic revisions must never manage the commission schema itself.

Migrations ``SET ROLE tillflow_commission_owner`` (alembic/env.py) so created
objects are owned by the owner role. That role deliberately has no ``CREATE``
on the database, so any schema DDL in a revision fails with
``InsufficientPrivilege`` -- and ``IF NOT EXISTS`` does not save it, because
Postgres checks the privilege before the existence test. Schema creation,
ownership and deletion belong to db-bootstrap.

The pre-``SET ROLE`` ``CREATE SCHEMA IF NOT EXISTS`` in env.py is exempt and
deliberate: it runs as the connecting role for local/CI convenience and is a
no-op in AWS. Only revision files are checked here.

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
    assert "0001_create_commission_schema.py" in names


@pytest.mark.parametrize("revision", _revisions(), ids=lambda p: p.name)
def test_revision_contains_no_schema_ddl(revision: Path):
    offenders = [
        line.strip()
        for line in _code_lines(revision.read_text())
        if SCHEMA_DDL.search(line)
    ]
    assert not offenders, (
        f"{revision.name} executes schema DDL: {offenders}. "
        "db-bootstrap owns the commission schema; the owner role the migration "
        "SET ROLEs into has no CREATE on the database."
    )


def test_0001_upgrade_and_downgrade_are_no_ops():
    source = (VERSIONS / "0001_create_commission_schema.py").read_text()
    body = _code_lines(source)

    # No calls of any kind in the revision body -- not just no schema DDL.
    assert not [line for line in body if "op." in line], (
        "0001 must stay a no-op: the commission schema is created and dropped "
        "by db-bootstrap only."
    )
    assert "def upgrade() -> None:" in source
    assert "def downgrade() -> None:" in source
