from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tillflow_shared.mpesa.fake import FakeMpesaAdapter
from tillflow_shared.mpesa.scenarios import FakeScenario

from payments.config import settings
from payments.deps import get_ledger_repository, get_mpesa_adapter, reset_runtime_state
from payments.main import app


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    reset_runtime_state()
    yield
    reset_runtime_state()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _stk_headers(key: str) -> dict[str, str]:
    return {"X-Tenant-Id": "tenant-a", "Idempotency-Key": key}


def _initiate(client: TestClient, *, key: str, scenario: FakeScenario) -> dict:
    response = client.post(
        "/payments/stk",
        headers=_stk_headers(key),
        json={
            "sale_id": str(uuid4()),
            "phone_number": "254712345678",
            "amount_minor_units": 1500,
            "fake_scenario": scenario.value,
        },
    )
    assert response.status_code == 202
    return response.json()


def _post_callback(client: TestClient, payload: dict, *, secret: str | None = None):
    secret = secret or settings.mpesa_callback_secret
    return client.post(f"/callbacks/mpesa/{secret}", json=payload)


def _ledger_entries(payment_id: str):
    ledger = get_ledger_repository(session=None)
    return asyncio.run(ledger.list_for_payment(UUID(payment_id)))


def test_callback_success_settles_paid_with_one_ledger_entry(client: TestClient) -> None:
    payment = _initiate(client, key="cb-success", scenario=FakeScenario.IMMEDIATE_SUCCESS)
    adapter = get_mpesa_adapter()
    assert isinstance(adapter, FakeMpesaAdapter)
    callbacks = adapter.drain_callbacks(payment["checkout_request_id"])
    assert len(callbacks) == 1

    response = _post_callback(client, callbacks[0].to_daraja_body())

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "paid"
    assert body["ledger_written"] is True

    entries = _ledger_entries(payment["payment_id"])
    assert len(entries) == 1
    assert entries[0].entry_type == "charge_confirmed"
    assert entries[0].amount_minor_units == 1500


def test_duplicate_callback_writes_ledger_once(client: TestClient) -> None:
    payment = _initiate(client, key="cb-dupe", scenario=FakeScenario.DUPLICATE_CALLBACK)
    adapter = get_mpesa_adapter()
    assert isinstance(adapter, FakeMpesaAdapter)
    callbacks = adapter.drain_callbacks(payment["checkout_request_id"])
    assert len(callbacks) == 2

    first = _post_callback(client, callbacks[0].to_daraja_body())
    second = _post_callback(client, callbacks[1].to_daraja_body())

    assert first.status_code == 200
    assert first.json()["ledger_written"] is True
    assert second.status_code == 200
    assert second.json()["ledger_written"] is False
    assert second.json()["state"] == "paid"
    assert len(_ledger_entries(payment["payment_id"])) == 1


def test_out_of_order_failure_then_success_ends_paid(client: TestClient) -> None:
    payment = _initiate(client, key="cb-ooo", scenario=FakeScenario.OUT_OF_ORDER_CALLBACK)
    adapter = get_mpesa_adapter()
    assert isinstance(adapter, FakeMpesaAdapter)
    callbacks = adapter.drain_callbacks(payment["checkout_request_id"])
    assert callbacks[0].result_code == 1
    assert callbacks[1].result_code == 0

    fail = _post_callback(client, callbacks[0].to_daraja_body())
    success = _post_callback(client, callbacks[1].to_daraja_body())

    assert fail.json()["state"] == "failed"
    assert success.json()["state"] == "paid"
    assert success.json()["ledger_written"] is True
    assert len(_ledger_entries(payment["payment_id"])) == 1


def test_failure_after_paid_is_ignored(client: TestClient) -> None:
    payment = _initiate(client, key="cb-paid-first", scenario=FakeScenario.IMMEDIATE_SUCCESS)
    adapter = get_mpesa_adapter()
    assert isinstance(adapter, FakeMpesaAdapter)
    success = adapter.drain_callbacks(payment["checkout_request_id"])[0]
    _post_callback(client, success.to_daraja_body())

    failure_body = {
        "Body": {
            "stkCallback": {
                "MerchantRequestID": f"{success.merchant_request_id}-late",
                "CheckoutRequestID": payment["checkout_request_id"],
                "ResultCode": 1,
                "ResultDesc": "late failure",
                "CallbackMetadata": {"Item": []},
            }
        }
    }
    response = _post_callback(client, failure_body)

    assert response.status_code == 200
    assert response.json()["reason"] == "ignored_failure_after_paid"
    assert response.json()["state"] == "paid"
    assert len(_ledger_entries(payment["payment_id"])) == 1


def test_bad_callback_secret_rejected(client: TestClient) -> None:
    payment = _initiate(client, key="cb-auth", scenario=FakeScenario.IMMEDIATE_SUCCESS)
    adapter = get_mpesa_adapter()
    assert isinstance(adapter, FakeMpesaAdapter)
    callbacks = adapter.drain_callbacks(payment["checkout_request_id"])

    response = _post_callback(client, callbacks[0].to_daraja_body(), secret="wrong-secret")

    assert response.status_code == 403
