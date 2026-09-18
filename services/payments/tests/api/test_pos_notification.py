"""Payments -> POS: reporting a settled payment ([ADR-004]).

POS owns sale state but cannot know whether M-Pesa took the money, so Payments
reports every settlement. These tests pin the contract POS depends on: one
report per settlement, carrying the tenant and a payment-derived idempotency
key, and a POS outage never undoing a settled payment.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from payments.clients.pos import result_idempotency_key
from payments.deps import get_pos_client, reset_runtime_state
from payments.main import app
from tillflow_shared.mpesa.scenarios import FakeScenario


class FakePosClient:
    """Records what Payments would send POS; set ``fail`` to take POS down."""

    def __init__(self) -> None:
        self.reports: list[dict] = []
        self.fail = False

    async def report_payment_result(self, payment) -> bool:
        if self.fail:
            raise ConnectionError("pos unreachable")
        self.reports.append(
            {
                "sale_id": str(payment.sale_id),
                "tenant_id": payment.tenant_id,
                "state": payment.state,
                "receipt": payment.mpesa_receipt_number,
                "idempotency_key": result_idempotency_key(payment),
            }
        )
        return True


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    reset_runtime_state()
    yield
    reset_runtime_state()
    app.dependency_overrides.pop(get_pos_client, None)


@pytest.fixture
def pos() -> FakePosClient:
    fake = FakePosClient()
    app.dependency_overrides[get_pos_client] = lambda: fake
    return fake


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _initiate(client: TestClient, *, sale_id: str, scenario: FakeScenario) -> dict:
    response = client.post(
        "/payments/stk",
        headers={"X-Tenant-Id": "tenant-a", "Idempotency-Key": f"stk-{sale_id}"},
        json={
            "sale_id": sale_id,
            "phone_number": "254796036246",
            "amount_minor_units": 1500,
            "fake_scenario": scenario.value,
        },
    )
    assert response.status_code == 202
    return response.json()


def _callback(client: TestClient, payment: dict, *, result_code: int = 0) -> dict:
    response = client.post(
        "/callbacks/mpesa/local-dev-callback-secret",
        json={
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": payment["merchant_request_id"],
                    "CheckoutRequestID": payment["checkout_request_id"],
                    "ResultCode": result_code,
                    "ResultDesc": "processed" if result_code == 0 else "insufficient funds",
                    "CallbackMetadata": {
                        "Item": [
                            {"Name": "Amount", "Value": 15},
                            {"Name": "MpesaReceiptNumber", "Value": "RCPTPOS1"},
                        ]
                    },
                }
            }
        },
    )
    assert response.status_code == 200
    return response.json()


def test_paid_callback_is_reported_to_pos(client, pos):
    sale_id = str(uuid4())
    payment = _initiate(client, sale_id=sale_id, scenario=FakeScenario.IMMEDIATE_SUCCESS)

    _callback(client, payment)

    assert len(pos.reports) == 1
    report = pos.reports[0]
    assert report["sale_id"] == sale_id
    assert report["tenant_id"] == "tenant-a"
    assert report["state"] == "paid"
    assert report["receipt"] == "RCPTPOS1"
    assert report["idempotency_key"] == f"payment-result-{payment['payment_id']}"


def test_failed_callback_is_reported_to_pos(client, pos):
    sale_id = str(uuid4())
    payment = _initiate(client, sale_id=sale_id, scenario=FakeScenario.IMMEDIATE_SUCCESS)

    _callback(client, payment, result_code=1032)

    assert [r["state"] for r in pos.reports] == ["failed"]


def test_duplicate_callback_does_not_re_report(client, pos):
    """One settlement, one report — a replayed callback must not tell POS twice."""
    sale_id = str(uuid4())
    payment = _initiate(client, sale_id=sale_id, scenario=FakeScenario.IMMEDIATE_SUCCESS)

    _callback(client, payment)
    second = _callback(client, payment)

    assert second["reason"] == "duplicate_callback"
    assert len(pos.reports) == 1


def test_pos_being_down_does_not_fail_the_callback(client, pos):
    """Daraja must still get its 200, and the payment stays settled."""
    sale_id = str(uuid4())
    payment = _initiate(client, sale_id=sale_id, scenario=FakeScenario.IMMEDIATE_SUCCESS)
    pos.fail = True

    settled = _callback(client, payment)

    assert settled["state"] == "paid"
    assert pos.reports == []


def test_reconciliation_reports_the_outcome(client, pos):
    """The timeout path also tells POS — and re-reports if the callback's was lost."""
    sale_id = str(uuid4())
    payment = _initiate(client, sale_id=sale_id, scenario=FakeScenario.DELAYED_TIMEOUT)
    assert payment["state"] == "pending_reconciliation"
    assert pos.reports == []

    response = client.post(f"/payments/reconcile/{payment['payment_id']}")

    assert response.status_code == 200 and response.json()["state"] == "paid"
    assert [r["state"] for r in pos.reports] == ["paid"]


def test_no_pos_url_configured_still_settles(client):
    """POS_BASE_URL unset: payments settles, nobody is notified, nothing breaks."""
    sale_id = str(uuid4())
    payment = _initiate(client, sale_id=sale_id, scenario=FakeScenario.IMMEDIATE_SUCCESS)
    assert _callback(client, payment)["state"] == "paid"
