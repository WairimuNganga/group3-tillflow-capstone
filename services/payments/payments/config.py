import json

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url


def _url_from_credentials(raw: str) -> str:
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
    """Payments service configuration — secrets come from env / Secrets Manager."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    service_name: str = Field(default="payments", alias="SERVICE_NAME")
    git_commit_sha: str = Field(default="unknown", alias="GIT_COMMIT_SHA")
    database_url: str = Field(default="", alias="DATABASE_URL")
    db_credentials: str = Field(default="", alias="DB_CREDENTIALS", repr=False)
    mpesa_adapter: str = Field(default="fake", alias="MPESA_ADAPTER")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    # POS base URL for reporting settled payments back (Service Connect in AWS).
    # Empty means "do not notify" — payments still settles; POS is told when the
    # URL is configured, or by the next reconciliation run.
    pos_base_url: str = Field(default="", alias="POS_BASE_URL")

    # Unguessable path segment for Daraja callback URL ([ADR-007] / threat model TB5).
    mpesa_callback_secret: str = Field(
        default="local-dev-callback-secret", alias="MPESA_CALLBACK_SECRET"
    )

    @model_validator(mode="after")
    def _database_url_from_ecs_secret(self) -> "Settings":
        if not self.database_url and self.db_credentials:
            self.database_url = _url_from_credentials(self.db_credentials)
        return self

    @property
    def database_sync_url(self) -> str:
        """Sync driver URL for Alembic and the readiness probe."""
        if not self.database_url:
            return ""
        parsed = make_url(self.database_url)
        query = dict(parsed.query)
        if "ssl" in query:
            query["sslmode"] = query.pop("ssl")
        return parsed.set(drivername="postgresql+psycopg", query=query).render_as_string(
            hide_password=False
        )

    @property
    def database_libpq_dsn(self) -> str:
        sync = self.database_sync_url
        return sync.replace("postgresql+psycopg://", "postgresql://", 1) if sync else ""


settings = Settings()
