from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    service_name: str = Field(default="web", alias="SERVICE_NAME")
    git_commit_sha: str = Field(default="unknown", alias="GIT_COMMIT_SHA")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # POS over Service Connect in AWS; empty = demo mode with in-process fake.
    pos_base_url: str = Field(default="", alias="POS_BASE_URL")
    # Commission worker; empty = in-process fake (no ledgered/payout state).
    commission_base_url: str = Field(default="", alias="COMMISSION_BASE_URL")

    # Signing key for session cookies (override in deploy).
    session_secret: str = Field(
        default="local-dev-web-session-secret-change-me",
        alias="WEB_SESSION_SECRET",
        repr=False,
    )
    session_cookie_name: str = Field(default="tillflow_session", alias="WEB_SESSION_COOKIE")
    csrf_cookie_name: str = Field(default="tillflow_csrf", alias="WEB_CSRF_COOKIE")
    cookie_secure: bool = Field(default=False, alias="WEB_COOKIE_SECURE")


settings = Settings()
