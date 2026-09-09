from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from tillflow_shared.mpesa.exceptions import MpesaAuthError
from tillflow_shared.mpesa.settings import MpesaSettings


@dataclass
class _CachedToken:
    access_token: str
    expires_at_epoch: float


class OAuthTokenCache:
    """In-process Daraja OAuth token cache with expiry buffer."""

    def __init__(self, settings: MpesaSettings, *, expiry_buffer_seconds: int = 300) -> None:
        self._settings = settings
        self._expiry_buffer_seconds = expiry_buffer_seconds
        self._cached: _CachedToken | None = None

    def clear(self) -> None:
        self._cached = None

    async def get_access_token(self, client: httpx.AsyncClient) -> str:
        now = time.time()
        if self._cached and now < self._cached.expires_at_epoch:
            return self._cached.access_token

        token_url = f"{self._settings.daraja_base_url.rstrip('/')}/oauth/v1/generate"
        response = await client.get(
            token_url,
            params={"grant_type": "client_credentials"},
            auth=(self._settings.daraja_consumer_key, self._settings.daraja_consumer_secret),
        )
        if response.status_code != 200:
            raise MpesaAuthError(f"OAuth failed with status {response.status_code}")

        payload = response.json()
        access_token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        if not access_token or not expires_in:
            raise MpesaAuthError("OAuth response missing access_token or expires_in")

        self._cached = _CachedToken(
            access_token=access_token,
            expires_at_epoch=now + int(expires_in) - self._expiry_buffer_seconds,
        )
        return access_token
