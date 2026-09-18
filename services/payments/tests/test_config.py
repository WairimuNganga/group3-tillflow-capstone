"""Runtime DB wiring as ECS provides it: DB_CREDENTIALS JSON, TLS to RDS Proxy."""

import json

import psycopg

from payments.config import Settings

_CREDS = {
    "username": "tillflow_payments",
    "password": "p@ss:w/rd",
    "host": "devops-g3-db-proxy.proxy-example.us-west-1.rds.amazonaws.com",
    "port": 5432,
    "dbname": "tillflow",
    "schema": "payments",
    "sslmode": "require",
}


def test_database_url_built_from_ecs_secret(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_CREDENTIALS", json.dumps(_CREDS))
    s = Settings(_env_file=None)

    assert s.database_url.startswith("postgresql+asyncpg://tillflow_payments:")
    assert "ssl=require" in s.database_url
    assert "sslmode=require" in s.database_sync_url
    info = psycopg.conninfo.conninfo_to_dict(s.database_libpq_dsn)
    assert info["password"] == "p@ss:w/rd"
    assert info["host"] == _CREDS["host"] and info["sslmode"] == "require"


def test_explicit_database_url_wins(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/tillflow")
    monkeypatch.setenv("DB_CREDENTIALS", json.dumps(_CREDS))
    s = Settings(_env_file=None)

    assert s.database_url == "postgresql+asyncpg://u:p@localhost:5432/tillflow"
    assert s.database_libpq_dsn == "postgresql://u:p@localhost:5432/tillflow"
