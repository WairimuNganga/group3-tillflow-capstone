from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MpesaSettings(BaseSettings):
    """Adapter configuration — never log secret values."""

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False, extra="ignore")

    mpesa_adapter: Literal["fake", "sandbox"] = Field(default="fake", alias="MPESA_ADAPTER")

    daraja_base_url: str = Field(
        default="https://sandbox.safaricom.co.ke",
        alias="DARAJA_BASE_URL",
    )
    daraja_consumer_key: str = Field(default="", alias="DARAJA_CONSUMER_KEY")
    daraja_consumer_secret: str = Field(default="", alias="DARAJA_CONSUMER_SECRET")
    daraja_passkey: str = Field(default="", alias="DARAJA_PASSKEY")
    daraja_shortcode: str = Field(default="", alias="DARAJA_SHORTCODE")
    daraja_initiator: str = Field(default="", alias="DARAJA_INITIATOR")
    daraja_security_credential: str = Field(default="", alias="DARAJA_SECURITY_CREDENTIAL")
    daraja_stk_callback_url: str = Field(default="", alias="DARAJA_STK_CALLBACK_URL")
    daraja_b2c_result_url: str = Field(default="", alias="DARAJA_B2C_RESULT_URL")

    http_connect_timeout_seconds: float = Field(default=5.0, alias="MPESA_HTTP_CONNECT_TIMEOUT")
    http_read_timeout_seconds: float = Field(default=30.0, alias="MPESA_HTTP_READ_TIMEOUT")

    @property
    def adapter(self) -> Literal["fake", "sandbox"]:
        return self.mpesa_adapter
