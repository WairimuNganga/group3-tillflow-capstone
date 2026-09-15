from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from payments.deps import get_ledger_repository, reset_runtime_state
from payments.main import app


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    reset_runtime_state()
    yield
    reset_runtime_state()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


ORIGINATOR = "tenant-a:2026-09-14:attendant-7"


def _headers(key: str = ORIGINATOR) -> dict[str, str]:
    return {"X-Tenant-Id": "tenant-a", "Idempotency-Key": key}


def _body(**overrides: object) -> dict:
    payload = {
        "attendant_id": "attendant-7",
        "phone_number": "254712345678",
        "amount_minor_units": 50000,
        "originator_conversation_id": ORIGINATOR,
    }
    payload.update(overrides)
    return payload


def test_b2c_submit_then_result_completes_with_one_ledger(client: TestClient) -> None:
    submitted = client.post("/payments/b2c", headers=_headers(), json=_body())
    assert submitted.status_code == 202
    body = submitted.json()
    assert body["state"] == "submitted"
    assert body["conversation_id"]
    assert body["amount_whole_kes"] == 500

    result = client.post(
        "/payments/b2c/result",
        json={"conversation_id": body["conversation_id"], "success": True},
    )
    assert result.status_code == 200
    assert result.json()["state"] == "completed"

    # Result replay is idempotent — still one ledger line.
    again = client.post(
        "/payments/b2c/result",
        json={"conversation_id": body["conversation_id"], "success": True},
    )
    assert again.json()["state"] == "completed"

    ledger = get_ledger_repository(session=None)
    entries = asyncio.run(ledger.list_for_payout(UUID(body["payout_id"])))
    assert len(entries) == 1
    assert entries[0].entry_type == "payout_disbursed"
    assert entries[0].amount_minor_units == 50000


def test_b2c_idempotent_replay_does_not_create_second_payout(client: TestClient) -> None:
    first = client.post("/payments/b2c", headers=_headers(), json=_body())
    second = client.post("/payments/b2c", headers=_headers(), json=_body())

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json() == second.json()


def test_b2c_requires_matching_idempotency_key(client: TestClient) -> None:
    response = client.post(
        "/payments/b2c",
        headers=_headers("wrong-key"),
        json=_body(),
    )
    assert response.status_code == 400
    assert "Idempotency-Key" in response.json()["detail"]


def test_b2c_result_failure(client: TestClient) -> None:
    submitted = client.post("/payments/b2c", headers=_headers(), json=_body())
    conversation_id = submitted.json()["conversation_id"]

    result = client.post(
        "/payments/b2c/result",
        json={
            "conversation_id": conversation_id,
            "success": False,
            "result_desc": "insufficient float",
        },
    )
    assert result.status_code == 200
    assert result.json()["state"] == "failed"

    ledger = get_ledger_repository(session=None)
    entries = asyncio.run(ledger.list_for_payout(UUID(submitted.json()["payout_id"])))
    assert entries == []
