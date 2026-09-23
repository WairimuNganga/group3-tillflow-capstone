"""POS migrations must grant commission exactly the cross-schema read it needs.

A SELECT grant on a view is unusable without USAGE on the view's schema.
Revision 0003 granted SELECT on the three commission views but never USAGE on
the pos schema, the same defect that made the AWS daily close fail with
"permission denied for schema payments". It had not surfaced on the pos side
only because the close reads the payments view first.

db-bootstrap grants each service USAGE on its OWN schema only, so a legitimate
cross-schema read is declared by the owning schema's migration -- the pos owner
role owns both the schema and the views, and is the only role entitled to grant
on them.
"""

import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
GRANT_REVISION = VERSIONS / "0004_grant_commission_schema_usage.py"

# The three views commission actually reads. Anything beyond this list is a
# widening of the blast radius and should fail review, not just this test.
COMMISSION_VIEWS = [
    "pos.v_attendants_for_payout",
    "pos.v_commission_rates_current",
    "pos.v_sales_for_commission",
]


def test_commission_grant_migration_exists():
    assert GRANT_REVISION.exists(), (
        "pos must ship a migration granting commission USAGE on the pos "
        "schema; SELECT on a view alone is not enough to read it."
    )


def test_grant_covers_schema_usage():
    sql = GRANT_REVISION.read_text()
    assert re.search(r"GRANT\s+USAGE\s+ON\s+SCHEMA\s+pos\s+TO\s+tillflow_commission", sql), (
        "missing GRANT USAGE ON SCHEMA pos -- this is the half that was "
        "forgotten in 0003."
    )


def test_grant_covers_every_view_commission_reads():
    sql = GRANT_REVISION.read_text()
    granted = sorted(
        re.findall(
            r"GRANT\s+SELECT\s+ON\s+([a-z_.]+)\s+TO\s+tillflow_commission",
            sql,
        )
    )
    assert granted == COMMISSION_VIEWS, (
        f"expected grants on exactly {COMMISSION_VIEWS}, got {granted}"
    )


def test_commission_is_not_granted_raw_pos_tables():
    """Commission reads views, never pos.sales or pos.attendants directly."""
    sql = GRANT_REVISION.read_text()
    granted = re.findall(r"GRANT\s+SELECT\s+ON\s+([a-z_.]+)\s+TO\s+tillflow_commission", sql)
    assert all(".v_" in target for target in granted), (
        f"only views may be granted to commission, got: {granted}"
    )


def test_grant_is_guarded_on_role_existence():
    """db-bootstrap creates tillflow_commission; local and CI databases do not."""
    sql = GRANT_REVISION.read_text()
    assert "pg_roles" in sql and "tillflow_commission" in sql


def test_grant_migration_is_reversible():
    sql = GRANT_REVISION.read_text()
    assert "REVOKE USAGE ON SCHEMA pos FROM tillflow_commission" in sql


def test_revision_chain_is_linear_and_unbroken():
    """A duplicate or dangling down_revision makes `upgrade head` ambiguous."""
    revisions, downs = {}, {}
    for path in VERSIONS.glob("*.py"):
        if path.name == "__init__.py":
            continue
        text = path.read_text()
        rev = re.search(r'^revision:\s*str\s*=\s*"([^"]+)"', text, re.M)
        down = re.search(r'^down_revision[^=]*=\s*(?:"([^"]+)"|None)', text, re.M)
        assert rev, f"{path.name} has no revision id"
        revisions[rev.group(1)] = path.name
        downs[rev.group(1)] = down.group(1) if down and down.group(1) else None

    assert len(revisions) == len(list(VERSIONS.glob("*.py"))), "duplicate revision id"
    roots = [r for r, d in downs.items() if d is None]
    assert len(roots) == 1, f"expected exactly one root revision, got {roots}"
    for rev, down in downs.items():
        if down is not None:
            assert down in revisions, f"{rev} points at unknown down_revision {down}"
    heads = set(revisions) - {d for d in downs.values() if d}
    assert len(heads) == 1, f"expected a single head, got {sorted(heads)}"
