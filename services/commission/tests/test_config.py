"""Runtime and migration DB wiring as ECS provides it.

Runtime connects as the NOBYPASSRLS role from `DB_CREDENTIALS`; Alembic
connects as a member of `tillflow_commission_owner` from
`COMMISSION_DB_ADMIN_URL` so created objects are owned by the owner role, not
the runtime role (ADR-005).
"""

import json

import psycopg

from commission.config import Settings

_CREDS = {
    "username": "tillflow_commission",
    "password": "p@ss:w/rd",
    "host": "devops-g3-db-proxy.proxy-example.us-west-1.rds.amazonaws.com",
    "port": 5432,
    "dbname": "tillflow",
    "schema": "commission",
    "sslmode": "require",
}

_ADMIN_URL = (
    "postgresql+asyncpg://tillflow_admin:adm%40n%3Ap%2Fss"
    "@devops-g3-db-proxy.proxy-example.us-west-1.rds.amazonaws.com:5432"
    "/tillflow?ssl=require"
)


def _dsn(url: str) -> dict:
    return psycopg.conninfo.conninfo_to_dict(
        url.replace("postgresql+psycopg://", "postgresql://", 1)
    )


# --- Runtime connection ------------------------------------------------------


def test_database_url_built_from_ecs_secret(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_CREDENTIALS", json.dumps(_CREDS))
    s = Settings(_env_file=None)

    assert s.database_url.startswith("postgresql+asyncpg://tillflow_commission:")
    assert "ssl=require" in s.database_url
    assert "sslmode=require" in s.database_sync_url
    info = psycopg.conninfo.conninfo_to_dict(s.database_libpq_dsn)
    assert info["password"] == "p@ss:w/rd"  # special chars survive escaping
    assert info["host"] == _CREDS["host"] and info["sslmode"] == "require"


def test_no_db_configured_means_memory_mode(monkeypatch):
    for var in ("DATABASE_URL", "DB_CREDENTIALS", "COMMISSION_DB_ADMIN_URL"):
        monkeypatch.delenv(var, raising=False)
    s = Settings(_env_file=None)

    assert s.database_url == ""
    assert s.database_libpq_dsn == ""
    # Nothing to migrate against — alembic/env.py raises rather than silently
    # connecting as whatever DATABASE_URL happens to be.
    assert s.database_admin_sync_url == ""


# --- Migration (admin) connection --------------------------------------------


def test_migrations_use_admin_url_not_runtime_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_CREDENTIALS", json.dumps(_CREDS))
    monkeypatch.setenv("COMMISSION_DB_ADMIN_URL", _ADMIN_URL)
    s = Settings(_env_file=None)

    assert _dsn(s.database_admin_sync_url)["user"] == "tillflow_admin"
    assert _dsn(s.database_libpq_dsn)["user"] == "tillflow_commission"


def test_admin_url_converts_asyncpg_to_psycopg(monkeypatch):
    monkeypatch.setenv("COMMISSION_DB_ADMIN_URL", _ADMIN_URL)
    s = Settings(_env_file=None)

    assert s.database_admin_sync_url.startswith("postgresql+psycopg://")
    assert "+asyncpg" not in s.database_admin_sync_url


def test_admin_url_translates_ssl_to_sslmode(monkeypatch):
    monkeypatch.setenv("COMMISSION_DB_ADMIN_URL", _ADMIN_URL)
    s = Settings(_env_file=None)

    # asyncpg spells it `ssl=`; libpq/psycopg only understands `sslmode=`.
    assert "sslmode=require" in s.database_admin_sync_url
    assert "ssl=require" not in s.database_admin_sync_url.replace("sslmode=require", "")


def test_admin_password_with_reserved_url_characters_survives(monkeypatch):
    monkeypatch.setenv("COMMISSION_DB_ADMIN_URL", _ADMIN_URL)
    s = Settings(_env_file=None)

    info = _dsn(s.database_admin_sync_url)
    # @ : / all round-trip — the RDS master password is generated, not curated.
    assert info["password"] == "adm@n:p/ss"
    assert info["host"] == "devops-g3-db-proxy.proxy-example.us-west-1.rds.amazonaws.com"
    assert info["dbname"] == "tillflow"


def test_admin_url_falls_back_to_runtime_url(monkeypatch):
    monkeypatch.delenv("COMMISSION_DB_ADMIN_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/tillflow")
    s = Settings(_env_file=None)

    assert s.database_admin_sync_url == "postgresql+psycopg://u:p@localhost:5432/tillflow"


def test_default_migration_role_is_the_owner_role(monkeypatch):
    monkeypatch.delenv("COMMISSION_MIGRATION_ROLE", raising=False)
    s = Settings(_env_file=None)

    assert s.migration_role == "tillflow_commission_owner"
