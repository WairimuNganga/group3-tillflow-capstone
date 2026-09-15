from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from payments.config import settings

_log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for the payments schema."""


engine = (
    create_async_engine(settings.database_url, pool_pre_ping=True)
    if settings.database_url
    else None
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False) if engine else None


def is_db_ready() -> bool:
    """Readiness probe: Postgres reachable with a trivial query."""
    sync_url = settings.database_sync_url
    if not sync_url:
        _log.warning("DATABASE_URL is not configured")
        return False

    try:
        import psycopg

        with psycopg.connect(sync_url, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        _log.exception("database readiness check failed")
        return False


async def get_session() -> AsyncSession:
    """FastAPI dependency for request-scoped DB sessions (used from Phase 2 onward)."""
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL is not configured")

    async with SessionLocal() as session:
        yield session


async def verify_async_connection() -> None:
    """Smoke-test helper for integration tests against a real database."""
    if engine is None:
        raise RuntimeError("DATABASE_URL is not configured")

    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
