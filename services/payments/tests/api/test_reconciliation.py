from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from payments.deps import get_ledger_repository, reset_runtime_state
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


def _headers(key: str) -> dict[str, str]:
    return {"X-Tenant-Id": "tenant-a", "Idempotency-Key": key}


def test_timeout_then_reconcile_settles_paid_once(client: TestClient) -> None:
    stk = client.post(
        "/payments/stk",
        headers=_headers("recon-timeout"),
        json={
            "sale_id": str(uuid4()),
            "phone_number": "254712345678",
            "amount_minor_units": 1500,
            "fake_scenario": FakeScenario.DELAYED_TIMEOUT.value,
        },
    )
    assert stk.status_code == 202
    body = stk.json()
    assert body["state"] == "pending_reconciliation"
    assert body["checkout_request_id"]

    drained = client.post("/payments/reconcile/outbox")
    assert drained.status_code == 200
    payload = drained.json()
    assert payload["processed"] == 1
    assert payload["results"][0]["state"] == "paid"
    assert payload["results"][0]["ledger_written"] is True

    # Replay worker is idempotent — already terminal, no second ledger line.
    again = client.post(f"/payments/reconcile/{body['payment_id']}")
    assert again.status_code == 200
    assert again.json()["reason"] == "already_terminal"

    ledger = get_ledger_repository(session=None)
    entries = asyncio.run(ledger.list_for_payment(UUID(body["payment_id"])))
    assert len(entries) == 1
    assert entries[0].entry_type == "charge_confirmed"


def test_reconcile_outbox_empty_when_no_timeouts(client: TestClient) -> None:
    response = client.post("/payments/reconcile/outbox")
    assert response.status_code == 200
    assert response.json()["processed"] == 0
