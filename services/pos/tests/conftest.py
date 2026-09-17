"""Test harness for the POS service.

Two modes:

- **Memory** (`client` fixture) — no database. Exercises onboarding, idempotency,
  totals, FK validation, and the state machine through the API. Always runs, so
  `pytest` is green on a laptop / CI with no Postgres (mirrors payments).
- **Postgres** (`pg_client`, `runtime_conn`, `admin_conn`) — needs a real
  Postgres for RLS / FORCE / composite FKs. Skips unless `POS_TEST_ADMIN_DSN`
  is set (a superuser DSN). Applies the real Alembic migration as the owner role
  and drives the app as the NOBYPASSRLS `tillflow_pos` role.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

# Tests don't run an OTel collector; keep telemetry instrumented but unexported.
os.environ.setdefault("TILLFLOW_TELEMETRY_EXPORT", "none")

import asyncpg  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

ADMIN_DSN = os.getenv("POS_TEST_ADMIN_DSN")  # libpq DSN for a superuser
RUNTIME_PW = os.getenv("POS_TEST_RUNTIME_PASSWORD", "pos_test_pw")

_POS_DIR = Path(__file__).resolve().parents[1]
_TABLES = ["sale_items", "sales", "commission_rates", "tills", "users", "tenants"]

_BOOTSTRAP_SQL = f"""
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='tillflow_pos_owner') THEN
    CREATE ROLE tillflow_pos_owner NOLOGIN NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='tillflow_pos') THEN
    CREATE ROLE tillflow_pos LOGIN PASSWORD '{RUNTIME_PW}' NOBYPASSRLS;
  ELSE
    ALTER ROLE tillflow_pos WITH LOGIN PASSWORD '{RUNTIME_PW}' NOBYPASSRLS;
  END IF;
  EXECUTE 'GRANT tillflow_pos_owner TO ' || quote_ident(current_user);
END $$;

CREATE SCHEMA IF NOT EXISTS pos AUTHORIZATION tillflow_pos_owner;
GRANT CONNECT ON DATABASE {{dbname}} TO tillflow_pos;
GRANT USAGE ON SCHEMA pos TO tillflow_pos;
ALTER DEFAULT PRIVILEGES FOR ROLE tillflow_pos_owner IN SCHEMA pos
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tillflow_pos;
ALTER DEFAULT PRIVILEGES FOR ROLE tillflow_pos_owner IN SCHEMA pos
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO tillflow_pos;
ALTER ROLE tillflow_pos SET search_path = pos;
"""


def _dbname() -> str:
    return urlparse(ADMIN_DSN).path.lstrip("/") or "postgres"


def _async_url(user: str, password: str) -> str:
    p = urlparse(ADMIN_DSN)
    return f"postgresql+asyncpg://{user}:{password}@{p.hostname}:{p.port or 5432}/{_dbname()}"


def _admin_async_url() -> str:
    return ADMIN_DSN.replace("postgresql://", "postgresql+asyncpg://", 1)


def _runtime_dsn() -> str:
    p = urlparse(ADMIN_DSN)
    return f"postgresql://tillflow_pos:{RUNTIME_PW}@{p.hostname}:{p.port or 5432}/{_dbname()}"


def _psql(sql: str) -> None:
    subprocess.run(
        ["psql", ADMIN_DSN, "-v", "ON_ERROR_STOP=1", "--no-psqlrc", "-q"],
        input=sql, text=True, check=True, capture_output=True,
    )


@pytest.fixture(scope="session")
def _pg() -> dict:
    if not ADMIN_DSN:
        pytest.skip("POS_TEST_ADMIN_DSN not set — skipping Postgres-backed POS tests")
    try:
        _psql(_BOOTSTRAP_SQL.format(dbname=_dbname()))
        env = {
            **os.environ,
            "POS_DB_ADMIN_URL": _admin_async_url(),
            "DATABASE_URL": _async_url("tillflow_pos", RUNTIME_PW),
        }
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_POS_DIR, env=env, check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        pytest.fail(f"DB setup failed: {exc.stderr or exc.stdout}")
    return {"runtime_url": _async_url("tillflow_pos", RUNTIME_PW)}


# --- memory mode ---------------------------------------------------------------
@pytest_asyncio.fixture
async def client() -> AsyncClient:
    """In-memory app (no DATABASE_URL)."""
    import pos.db as dbmod
    from pos.config import settings
    from pos.deps import reset_runtime_state

    if dbmod.engine is not None:
        await dbmod.engine.dispose()
    dbmod.engine = None
    dbmod.SessionLocal = None
    settings.database_url = ""
    reset_runtime_state()

    from pos.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://pos.test") as c:
        yield c


# --- postgres mode -------------------------------------------------------------
@pytest_asyncio.fixture
async def admin_conn(_pg: dict) -> asyncpg.Connection:
    """Superuser connection: setup/assertions. Bypasses RLS — sees all rows."""
    conn = await asyncpg.connect(ADMIN_DSN)
    await conn.execute("TRUNCATE " + ", ".join(f"pos.{t}" for t in _TABLES) + " CASCADE")
    try:
        yield conn
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def pg_client(_pg: dict, admin_conn: asyncpg.Connection) -> AsyncClient:
    """App bound to Postgres as the tillflow_pos runtime role."""
    import pos.db as dbmod
    from pos.config import settings

    if dbmod.engine is not None:
        await dbmod.engine.dispose()
    settings.database_url = _pg["runtime_url"]
    dbmod.engine = create_async_engine(_pg["runtime_url"], pool_pre_ping=True)
    dbmod.SessionLocal = async_sessionmaker(dbmod.engine, expire_on_commit=False)

    from pos.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://pos.test") as c:
        yield c

    await dbmod.engine.dispose()
    dbmod.engine = None
    dbmod.SessionLocal = None


@pytest_asyncio.fixture
async def runtime_conn(_pg: dict) -> asyncpg.Connection:
    """Direct connection AS tillflow_pos (NOBYPASSRLS) — for DB-level RLS proof."""
    conn = await asyncpg.connect(_runtime_dsn())
    try:
        yield conn
    finally:
        await conn.close()


# --- helpers -------------------------------------------------------------------
async def onboard(client: AsyncClient, *, name, phone, shortcode, att_phone) -> dict:
    r = await client.post("/tenants", json={"name": name, "owner_phone": phone, "owner_name": "O"})
    assert r.status_code == 201, r.text
    tid = r.json()["tenant"]["id"]
    headers = {"X-Tenant-Id": tid}
    till = await client.post("/tills", headers=headers, json={"name": "T", "shortcode": shortcode})
    att = await client.post(
        "/attendants", headers=headers, json={"phone": att_phone, "display_name": "A"}
    )
    assert till.status_code == 201 and att.status_code == 201
    return {
        "id": tid,
        "headers": headers,
        "till_id": till.json()["id"],
        "attendant_id": att.json()["id"],
    }


def sale_payload(tenant: dict, **overrides) -> dict:
    payload = {
        "till_id": tenant["till_id"],
        "attendant_id": tenant["attendant_id"],
        "items": [
            {"name": "Sukuma", "quantity": 3, "unit_price_minor": 2000},
            {"name": "Bread", "quantity": 1, "unit_price_minor": 6500},
        ],
    }
    payload.update(overrides)
    return payload


def new_key() -> str:
    return f"key-{uuid.uuid4()}"
