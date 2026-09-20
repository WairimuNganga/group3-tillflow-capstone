from fastapi.testclient import TestClient

from commission.main import app


def test_health():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "commission"
    assert body["status"] == "ok"


def test_ready_without_database():
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 200
