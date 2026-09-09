import time

import httpx
import pytest

from tillflow_shared.mpesa.oauth import OAuthTokenCache
from tillflow_shared.mpesa.settings import MpesaSettings


@pytest.mark.asyncio
async def test_oauth_token_is_cached_until_near_expiry() -> None:
    settings = MpesaSettings(
        MPESA_ADAPTER="sandbox",
        DARAJA_BASE_URL="https://sandbox.example.test",
        DARAJA_CONSUMER_KEY="key",
        DARAJA_CONSUMER_SECRET="secret",
    )
    cache = OAuthTokenCache(settings, expiry_buffer_seconds=60)
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200,
            json={"access_token": f"token-{calls['count']}", "expires_in": 3600},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url=settings.daraja_base_url,
        transport=transport,
    ) as client:
        first = await cache.get_access_token(client)
        second = await cache.get_access_token(client)

    assert first == second == "token-1"
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_oauth_token_refreshes_after_expiry() -> None:
    settings = MpesaSettings(
        MPESA_ADAPTER="sandbox",
        DARAJA_BASE_URL="https://sandbox.example.test",
        DARAJA_CONSUMER_KEY="key",
        DARAJA_CONSUMER_SECRET="secret",
    )
    cache = OAuthTokenCache(settings, expiry_buffer_seconds=0)
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200,
            json={"access_token": f"token-{calls['count']}", "expires_in": 1},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url=settings.daraja_base_url,
        transport=transport,
    ) as client:
        first = await cache.get_access_token(client)
        time.sleep(1.1)
        second = await cache.get_access_token(client)

    assert first == "token-1"
    assert second == "token-2"
    assert calls["count"] == 2
