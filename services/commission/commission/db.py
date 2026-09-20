from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from commission.config import settings

_log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for the commission schema."""


engine = (
    create_async_engine(settings.database_url, pool_pre_ping=True)
    if settings.database_url
    else None
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False) if engine else None


def is_db_ready() -> bool:
    dsn = settings.database_libpq_dsn
    if not dsn:
        _log.warning("DATABASE_URL is not configured")
        return False

    try:
        import psycopg

        with psycopg.connect(dsn, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        _log.exception("database readiness check failed")
        return False


async def get_session() -> AsyncSession:
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL is not configured")

    async with SessionLocal() as session:
        yield session


async def verify_async_connection() -> None:
    if engine is None:
        raise RuntimeError("DATABASE_URL is not configured")

    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
