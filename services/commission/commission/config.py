import json

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url


def _url_from_credentials(raw: str) -> str:
    """Async URL from the ECS-injected ``commission`` entry of the
    ``devops-g3/db`` secret (``{username, password, host, port, dbname,
    sslmode}``). RDS Proxy has ``require_tls = true``, so TLS is on unless the
    secret says otherwise."""
    creds = json.loads(raw)
    url = URL.create(
        "postgresql+asyncpg",
        username=creds["username"],
        password=creds["password"],
        host=creds["host"],
        port=int(creds.get("port", 5432)),
        database=creds["dbname"],
        query={"ssl": creds.get("sslmode", "require")},
    )
    return url.render_as_string(hide_password=False)


class Settings(BaseSettings):
    """Commission worker configuration — secrets from env / Secrets Manager."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    service_name: str = Field(default="commission", alias="SERVICE_NAME")
    git_commit_sha: str = Field(default="unknown", alias="GIT_COMMIT_SHA")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    database_url: str = Field(default="", alias="DATABASE_URL")
    db_credentials: str = Field(default="", alias="DB_CREDENTIALS", repr=False)

    payments_base_url: str = Field(default="", alias="PAYMENTS_BASE_URL")
    payout_queue_url: str = Field(default="", alias="PAYOUT_QUEUE_URL")

    # When true, lifespan starts the SQS/in-memory consumer loop.
    worker_enabled: bool = Field(default=True, alias="COMMISSION_WORKER_ENABLED")

    # Migration/admin connection: a role that is a member of
    # `tillflow_commission_owner` (RDS master in AWS; the superuser locally).
    # Alembic uses this and switches to the owner role, so migrated objects are
    # owned by the owner and default-privilege grants apply (ADR-005 / G2
    # handover). Falls back to DATABASE_URL when unset.
    database_admin_url: str = Field(default="", alias="COMMISSION_DB_ADMIN_URL")

    # Owner role the migration switches into.
    migration_role: str = Field(
        default="tillflow_commission_owner", alias="COMMISSION_MIGRATION_ROLE"
    )

    @model_validator(mode="after")
    def _database_url_from_ecs_secret(self) -> "Settings":
        if not self.database_url and self.db_credentials:
            self.database_url = _url_from_credentials(self.db_credentials)
        return self

    @staticmethod
    def _to_sync(url: str) -> str:
        """asyncpg URL -> psycopg URL (asyncpg spells TLS `ssl=`, libpq `sslmode=`).

        Goes through ``make_url``/``render_as_string`` rather than string
        surgery so a password containing ``@``, ``:`` or ``/`` stays correctly
        escaped."""
        if not url:
            return ""
        parsed = make_url(url)
        query = dict(parsed.query)
        if "ssl" in query:
            query["sslmode"] = query.pop("ssl")
        return parsed.set(drivername="postgresql+psycopg", query=query).render_as_string(
            hide_password=False
        )

    @property
    def database_sync_url(self) -> str:
        """Sync driver URL for the readiness probe."""
        return self._to_sync(self.database_url)

    @property
    def database_libpq_dsn(self) -> str:
        """Plain ``postgresql://`` DSN for psycopg.connect — libpq rejects the
        SQLAlchemy ``+driver`` scheme."""
        sync = self.database_sync_url
        return sync.replace("postgresql+psycopg://", "postgresql://", 1) if sync else ""

    @property
    def database_admin_sync_url(self) -> str:
        """Sync driver URL Alembic runs migrations through."""
        return self._to_sync(self.database_admin_url or self.database_url)


settings = Settings()
