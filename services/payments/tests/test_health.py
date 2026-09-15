from fastapi.testclient import TestClient

from payments.main import app


def test_health_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "payments"
    assert "git_sha" in body


def test_ready_when_database_is_ready(monkeypatch) -> None:
    monkeypatch.setattr("payments.db.is_db_ready", lambda: True)
    client = TestClient(app)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_ready_when_database_is_not_ready(monkeypatch) -> None:
    monkeypatch.setattr("payments.db.is_db_ready", lambda: False)
    client = TestClient(app)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
