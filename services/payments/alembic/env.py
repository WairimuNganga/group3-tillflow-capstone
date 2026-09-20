from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

import payments.domain.models  # noqa: F401 — register models for autogenerate
import payments.idempotency.models  # noqa: F401
from alembic import context
from payments.config import settings
from payments.db import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    url = settings.database_admin_sync_url
    if not url:
        raise RuntimeError(
            "DATABASE_URL (or PAYMENTS_DB_ADMIN_URL) must be set to run Alembic"
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema="payments",
        include_schemas=True,
    )

    with context.begin_transaction():
        # Objects must be owned by the owner role so RLS + default-privilege
        # grants apply (ADR-005 / G2 handover).
        context.execute(f"SET ROLE {settings.migration_role}")
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema="payments",
            include_schemas=True,
        )

        with context.begin_transaction():
            # Switch to the owner role for the whole run so every created
            # object — tables AND the alembic_version table in the payments
            # schema — is owned by tillflow_payments_owner. The connecting role
            # must be a member of it. This must run INSIDE begin_transaction:
            # executing it first autobegins an outer transaction (SQLAlchemy
            # 2.0), Alembic then never commits, and the whole migration
            # silently rolls back when the connection closes.
            connection.execute(text(f"SET ROLE {settings.migration_role}"))
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
