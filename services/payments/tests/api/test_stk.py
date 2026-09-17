from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from payments.deps import reset_runtime_state
from payments.main import app
from tillflow_shared.mpesa.scenarios import FakeScenario


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    reset_runtime_state()
    yield
    reset_runtime_state()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _headers(key: str = "sale-key-1") -> dict[str, str]:
    return {"X-Tenant-Id": "tenant-a", "Idempotency-Key": key}


def _body(**overrides: object) -> dict:
    payload = {
        "sale_id": str(uuid4()),
        "phone_number": "254712345678",
        "amount_minor_units": 1500,
        "fake_scenario": FakeScenario.IMMEDIATE_SUCCESS.value,
    }
    payload.update(overrides)
    return payload


def test_stk_success_moves_to_stk_sent(client: TestClient) -> None:
    response = client.post("/payments/stk", headers=_headers(), json=_body())

    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "stk_sent"
    assert body["amount_whole_kes"] == 15
    assert body["checkout_request_id"]
    assert body["merchant_request_id"]


def test_stk_idempotent_replay_does_not_create_second_payment(client: TestClient) -> None:
    sale_id = str(uuid4())
    first = client.post(
        "/payments/stk",
        headers=_headers("key-replay"),
        json=_body(sale_id=sale_id),
    )
    second = client.post(
        "/payments/stk",
        headers=_headers("key-replay"),
        json=_body(sale_id=sale_id),
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json() == second.json()


def test_stk_timeout_stays_pending_reconciliation_not_failed(client: TestClient) -> None:
    response = client.post(
        "/payments/stk",
        headers=_headers("key-timeout"),
        json=_body(fake_scenario=FakeScenario.DELAYED_TIMEOUT.value),
    )

    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "pending_reconciliation"
    assert body["checkout_request_id"]
    assert body["merchant_request_id"]


def test_stk_requires_idempotency_headers(client: TestClient) -> None:
    response = client.post("/payments/stk", json=_body())

    assert response.status_code == 400
    assert "Idempotency-Key" in response.json()["detail"]


def test_stk_rejects_amount_that_rounds_to_zero_kes(client: TestClient) -> None:
    response = client.post(
        "/payments/stk",
        headers=_headers("key-tiny"),
        json=_body(amount_minor_units=49),
    )

    assert response.status_code == 400
