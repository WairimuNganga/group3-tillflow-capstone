from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @property
    def database_sync_url(self) -> str:
        """Sync driver URL for Alembic and the readiness probe."""
        if not self.database_url:
            return ""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")


settings = Settings()
