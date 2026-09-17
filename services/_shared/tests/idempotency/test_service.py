import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from tillflow_shared.idempotency import (
    IdempotencyHandle,
    IdempotencyReplay,
    InMemoryIdempotencyStore,
    idempotency_handle,
    register_idempotency_handlers,
)
from tillflow_shared.idempotency.service import IdempotencyService


@pytest.mark.asyncio
async def test_replay_returns_stored_response_without_reexecuting_handler() -> None:
    store = InMemoryIdempotencyStore()
    service = IdempotencyService(store, service_name="payments")
    calls = {"count": 0}

    async def handler() -> dict[str, str]:
        calls["count"] += 1
        return {"status": "paid"}

    handle = IdempotencyHandle(service, "tenant-a", "key-1")
    await handle.begin()
    await handler()
    await handle.complete(status_code=200, response_body={"status": "paid"})

    replay_handle = IdempotencyHandle(service, "tenant-a", "key-1")
    with pytest.raises(IdempotencyReplay) as exc:
        await replay_handle.begin()

    assert exc.value.record.response_body == {"status": "paid"}
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_same_key_different_tenants_are_isolated() -> None:
    store = InMemoryIdempotencyStore()
    service = IdempotencyService(store, service_name="payments")

    first = IdempotencyHandle(service, "tenant-a", "shared-key")
    await first.begin()
    await first.complete(status_code=200, response_body={"tenant": "a"})

    second = IdempotencyHandle(service, "tenant-b", "shared-key")
    await second.begin()
    await second.complete(status_code=200, response_body={"tenant": "b"})

    replay_a = IdempotencyHandle(service, "tenant-a", "shared-key")
    with pytest.raises(IdempotencyReplay) as replay:
        await replay_a.begin()
    assert replay.value.record.response_body == {"tenant": "a"}


def test_fastapi_dependency_replays_verbatim() -> None:
    store = InMemoryIdempotencyStore()
    app = FastAPI()
    register_idempotency_handlers(app)
    guard = idempotency_handle(store, service_name="payments")
    executions = {"count": 0}

    @app.post("/pay")
    async def pay(handle: IdempotencyHandle = Depends(guard)) -> JSONResponse:
        await handle.begin()
        executions["count"] += 1
        body = {"status": "pending", "execution": executions["count"]}
        await handle.complete(status_code=202, response_body=body)
        return JSONResponse(status_code=202, content=body)

    client = TestClient(app)
    headers = {"X-Tenant-Id": "tenant-a", "Idempotency-Key": "key-abc"}

    first = client.post("/pay", headers=headers)
    second = client.post("/pay", headers=headers)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json() == second.json()
    assert executions["count"] == 1


def test_fastapi_requires_headers() -> None:
    store = InMemoryIdempotencyStore()
    app = FastAPI()
    register_idempotency_handlers(app)
    guard = idempotency_handle(store, service_name="payments")

    @app.post("/pay")
    async def pay(handle: IdempotencyHandle = Depends(guard)) -> dict[str, str]:
        await handle.begin()
        return {"status": "ok"}

    client = TestClient(app)
    response = client.post("/pay")

    assert response.status_code == 400
