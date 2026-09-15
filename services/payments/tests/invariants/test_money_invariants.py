"""Crown-jewel money invariants ([ADR-004]).

These tests are the G2 / defence proof pack for Payments + integrity.
Run with:

    cd services/payments
    TILLFLOW_TELEMETRY_EXPORT=none MPESA_ADAPTER=fake pytest tests/invariants -v
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from payments.config import settings
from payments.deps import (
    get_ledger_repository,
    get_mpesa_adapter,
    get_payment_repository,
    get_payout_repository,
    reset_runtime_state,
)
from payments.main import app
from tillflow_shared.money import from_whole_kes, to_whole_kes
from tillflow_shared.mpesa.fake import FakeMpesaAdapter
from tillflow_shared.mpesa.scenarios import FakeScenario


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    reset_runtime_state()
    yield
    reset_runtime_state()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _stk_headers(tenant: str, key: str) -> dict[str, str]:
    return {"X-Tenant-Id": tenant, "Idempotency-Key": key}


def _initiate_stk(
    client: TestClient,
    *,
    tenant: str,
    key: str,
    scenario: FakeScenario,
    sale_id: str | None = None,
    amount_minor_units: int = 1500,
) -> dict:
    response = client.post(
        "/payments/stk",
        headers=_stk_headers(tenant, key),
        json={
            "sale_id": sale_id or str(uuid4()),
            "phone_number": "254712345678",
            "amount_minor_units": amount_minor_units,
            "fake_scenario": scenario.value,
        },
    )
    assert response.status_code in {200, 202}
    return response.json()


def _post_callback(client: TestClient, payload: dict) -> dict:
    response = client.post(
        f"/callbacks/mpesa/{settings.mpesa_callback_secret}",
        json=payload,
    )
    assert response.status_code == 200
    return response.json()


def _ledger_for_payment(payment_id: str):
    ledger = get_ledger_repository(session=None)
    return asyncio.run(ledger.list_for_payment(UUID(payment_id)))


def _ledger_for_payout(payout_id: str):
    ledger = get_ledger_repository(session=None)
    return asyncio.run(ledger.list_for_payout(UUID(payout_id)))


# ---------------------------------------------------------------------------
# 1. Money is integer minor units; convert only at the M-Pesa boundary
# ---------------------------------------------------------------------------


def test_kes_boundary_is_integer_and_round_trip_safe() -> None:
    assert to_whole_kes(149) == 1
    assert to_whole_kes(150) == 2
    assert from_whole_kes(2) == 200
    assert to_whole_kes(from_whole_kes(17)) == 17


def test_stk_persists_both_minor_and_whole_kes(client: TestClient) -> None:
    body = _initiate_stk(
        client,
        tenant="tenant-a",
        key="inv-kes",
        scenario=FakeScenario.IMMEDIATE_SUCCESS,
        amount_minor_units=1500,
    )
    assert body["amount_minor_units"] == 1500
    assert body["amount_whole_kes"] == 15
    assert isinstance(body["amount_minor_units"], int)
    assert isinstance(body["amount_whole_kes"], int)


# ---------------------------------------------------------------------------
# 2. STK initiation is idempotent — same key ⇒ one charge attempt
# ---------------------------------------------------------------------------


def test_stk_idempotency_no_double_charge(client: TestClient) -> None:
    sale_id = str(uuid4())
    first = _initiate_stk(
        client,
        tenant="tenant-a",
        key="inv-stk-idem",
        scenario=FakeScenario.IMMEDIATE_SUCCESS,
        sale_id=sale_id,
    )
    second = _initiate_stk(
        client,
        tenant="tenant-a",
        key="inv-stk-idem",
        scenario=FakeScenario.IMMEDIATE_SUCCESS,
        sale_id=sale_id,
    )

    assert first == second
    assert first["payment_id"] == second["payment_id"]

    adapter = get_mpesa_adapter()
    assert isinstance(adapter, FakeMpesaAdapter)
    # One STK record in the fake = one Daraja call.
    assert len(adapter._stk_records) == 1  # noqa: SLF001 — invariant proof


# ---------------------------------------------------------------------------
# 3. Timeout ≠ decline → reconcile via query → one ledger effect
# ---------------------------------------------------------------------------


def test_timeout_stays_pending_then_resolves_once(client: TestClient) -> None:
    body = _initiate_stk(
        client,
        tenant="tenant-a",
        key="inv-timeout",
        scenario=FakeScenario.DELAYED_TIMEOUT,
    )
    assert body["state"] == "pending_reconciliation"
    assert body["state"] != "failed"
    assert body["checkout_request_id"]

    drained = client.post("/payments/reconcile/outbox")
    assert drained.status_code == 200
    results = drained.json()["results"]
    assert len(results) == 1
    assert results[0]["state"] == "paid"
    assert results[0]["ledger_written"] is True

    # Worker / client retry cannot create a second charge.
    again = client.post(f"/payments/reconcile/{body['payment_id']}")
    assert again.json()["reason"] == "already_terminal"
    assert len(_ledger_for_payment(body["payment_id"])) == 1


# ---------------------------------------------------------------------------
# 4. Callback processing is idempotent + order-independent
# ---------------------------------------------------------------------------


def test_callback_replay_one_ledger_entry(client: TestClient) -> None:
    payment = _initiate_stk(
        client,
        tenant="tenant-a",
        key="inv-dupe-cb",
        scenario=FakeScenario.DUPLICATE_CALLBACK,
    )
    adapter = get_mpesa_adapter()
    assert isinstance(adapter, FakeMpesaAdapter)
    callbacks = adapter.drain_callbacks(payment["checkout_request_id"])
    assert len(callbacks) == 2

    first = _post_callback(client, callbacks[0].to_daraja_body())
    second = _post_callback(client, callbacks[1].to_daraja_body())

    assert first["state"] == "paid"
    assert first["ledger_written"] is True
    assert second["state"] == "paid"
    assert second["ledger_written"] is False
    assert len(_ledger_for_payment(payment["payment_id"])) == 1


def test_out_of_order_callbacks_settle_once(client: TestClient) -> None:
    payment = _initiate_stk(
        client,
        tenant="tenant-a",
        key="inv-ooo",
        scenario=FakeScenario.OUT_OF_ORDER_CALLBACK,
    )
    adapter = get_mpesa_adapter()
    assert isinstance(adapter, FakeMpesaAdapter)
    callbacks = adapter.drain_callbacks(payment["checkout_request_id"])
    assert callbacks[0].result_code == 1
    assert callbacks[1].result_code == 0

    fail = _post_callback(client, callbacks[0].to_daraja_body())
    success = _post_callback(client, callbacks[1].to_daraja_body())

    assert fail["state"] == "failed"
    assert success["state"] == "paid"
    assert success["ledger_written"] is True
    assert len(_ledger_for_payment(payment["payment_id"])) == 1


# ---------------------------------------------------------------------------
# 5. Replay never double-pays (B2C)
# ---------------------------------------------------------------------------


def test_b2c_replay_no_double_payout(client: TestClient) -> None:
    originator = "tenant-a:2026-09-14:att-inv"
    headers = _stk_headers("tenant-a", originator)
    payload = {
        "attendant_id": "att-inv",
        "phone_number": "254712345678",
        "amount_minor_units": 50000,
        "originator_conversation_id": originator,
    }

    first = client.post("/payments/b2c", headers=headers, json=payload)
    second = client.post("/payments/b2c", headers=headers, json=payload)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json() == second.json()

    conversation_id = first.json()["conversation_id"]
    client.post(
        "/payments/b2c/result",
        json={"conversation_id": conversation_id, "success": True},
    )
    client.post(
        "/payments/b2c/result",
        json={"conversation_id": conversation_id, "success": True},
    )

    payout_id = first.json()["payout_id"]
    assert len(_ledger_for_payout(payout_id)) == 1

    payouts = get_payout_repository(session=None)
    # Only one payout row for this originator.
    stored = asyncio.run(
        payouts.get_by_tenant_and_originator("tenant-a", originator)
    )
    assert stored is not None
    assert str(stored.id) == payout_id


# ---------------------------------------------------------------------------
# 6. Cross-tenant isolation on idempotency keys (threat model M1)
# ---------------------------------------------------------------------------


def test_cross_tenant_idempotency_does_not_leak_response(client: TestClient) -> None:
    shared_key = "shared-client-key"
    sale_a = str(uuid4())
    sale_b = str(uuid4())

    a = _initiate_stk(
        client,
        tenant="tenant-a",
        key=shared_key,
        scenario=FakeScenario.IMMEDIATE_SUCCESS,
        sale_id=sale_a,
    )
    b = _initiate_stk(
        client,
        tenant="tenant-b",
        key=shared_key,
        scenario=FakeScenario.IMMEDIATE_SUCCESS,
        sale_id=sale_b,
    )

    assert a["tenant_id"] == "tenant-a"
    assert b["tenant_id"] == "tenant-b"
    assert a["payment_id"] != b["payment_id"]
    assert a["sale_id"] == sale_a
    assert b["sale_id"] == sale_b

    payments = get_payment_repository(session=None)
    pay_a = asyncio.run(payments.get_by_tenant_and_sale("tenant-a", UUID(sale_a)))
    pay_b = asyncio.run(payments.get_by_tenant_and_sale("tenant-b", UUID(sale_b)))
    assert pay_a is not None and pay_b is not None
    assert pay_a.id != pay_b.id
