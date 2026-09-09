from fastapi import FastAPI
from fastapi.testclient import TestClient

from tillflow_shared.health.routes import create_health_router


def test_health_and_ready_endpoints() -> None:
    app = FastAPI()
    app.include_router(create_health_router(service_name="payments", git_sha="abc123"))
    client = TestClient(app)

    health = client.get("/health")
    ready = client.get("/ready")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["service"] == "payments"
    assert health.json()["git_sha"] == "abc123"

    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"


def test_ready_returns_503_when_not_ready() -> None:
    app = FastAPI()
    app.include_router(
        create_health_router(service_name="payments", ready_check=lambda: False)
    )
    client = TestClient(app)

    ready = client.get("/ready")

    assert ready.status_code == 503
    assert ready.json()["status"] == "not_ready"
    assert client.get("/health").status_code == 200


def test_ready_check_exception_is_not_silently_healthy() -> None:
    def flaky_check() -> bool:
        raise RuntimeError("db connection pool exhausted")

    app = FastAPI()
    app.include_router(
        create_health_router(service_name="payments", ready_check=flaky_check)
    )
    client = TestClient(app, raise_server_exceptions=False)

    ready = client.get("/ready")

    assert ready.status_code == 503
