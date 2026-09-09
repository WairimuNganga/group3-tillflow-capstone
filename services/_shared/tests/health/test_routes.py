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
