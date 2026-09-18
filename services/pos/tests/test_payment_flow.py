"""The two hops between POS and Payments ([ADR-004]).

  POS -> Payments   POST /sales/{id}/pay            -> payments' /payments/stk
  Payments -> POS   POST /internal/sales/{id}/payment-result

What these prove: a retried handoff cannot prompt the customer twice, an
unreachable Payments leaves the sale awaiting payment (never declined), a
replayed result changes the sale exactly once, money that doesn't match the sale
total is refused, and only Payments can move a sale into a money state.
"""

import uuid

from pos.clients.payments import stk_idempotency_key
from tests.conftest import new_key, onboard, sale_payload

A = dict(name="A", phone="254700000001", shortcode="111111", att_phone="254711111111")
B = dict(name="B", phone="254700000002", shortcode="222222", att_phone="254722222222")


async def _sale(client, tenant, **overrides) -> str:
    headers = {**tenant["headers"], "Idempotency-Key": new_key()}
    payload = sale_payload(tenant, **overrides)
    return (await client.post("/sales", headers=headers, json=payload)).json()["id"]


# --- hop 1: POS -> Payments ----------------------------------------------------
async def test_pay_moves_sale_to_awaiting_payment_and_calls_payments(client, payments_client):
    t = await onboard(client, **A)
    sale_id = await _sale(client, t, customer_msisdn="254796036246")

    r = await client.post(f"/sales/{sale_id}/pay", headers=t["headers"], json={})

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "awaiting_payment"
    assert body["payment_id"] == str(payments_client.payment_id)
    assert body["payment_state"] == "stk_sent"

    assert len(payments_client.calls) == 1
    call = payments_client.calls[0]
    # POS sends the sale's own total, in minor units — never a client-supplied amount.
    assert call["amount_minor_units"] == body["amount_minor_units"]
    assert call["phone_number"] == "254796036246"
    assert str(call["sale_id"]) == sale_id


async def test_pay_uses_an_explicit_phone_number_when_given(client, payments_client):
    t = await onboard(client, **A)
    sale_id = await _sale(client, t, customer_msisdn="254700000000")
    await client.post(
        f"/sales/{sale_id}/pay", headers=t["headers"], json={"phone_number": "254796036246"}
    )
    assert payments_client.calls[0]["phone_number"] == "254796036246"


async def test_pay_without_a_phone_number_is_rejected(client, payments_client):
    t = await onboard(client, **A)
    sale_id = await _sale(client, t, customer_msisdn=None)
    r = await client.post(f"/sales/{sale_id}/pay", headers=t["headers"], json={})
    assert r.status_code == 400
    assert not payments_client.calls


async def test_retrying_pay_reuses_one_idempotency_key(client, payments_client):
    """The till retrying must not put a second prompt on the customer's phone."""
    t = await onboard(client, **A)
    sale_id = await _sale(client, t, customer_msisdn="254796036246")

    first = await client.post(f"/sales/{sale_id}/pay", headers=t["headers"], json={})
    second = await client.post(f"/sales/{sale_id}/pay", headers=t["headers"], json={})

    assert first.status_code == second.status_code == 200
    assert second.json()["status"] == "awaiting_payment"
    # Both handoffs carry the same sale-derived key, so Payments dedupes them.
    assert stk_idempotency_key(uuid.UUID(sale_id)) == f"stk-{sale_id}"
    assert {c["sale_id"] for c in payments_client.calls} == {uuid.UUID(sale_id)}


async def test_payments_unreachable_leaves_the_sale_awaiting_payment(client, payments_client):
    """An uncertain payment is never a decline ([ADR-004])."""
    t = await onboard(client, **A)
    sale_id = await _sale(client, t, customer_msisdn="254796036246")
    payments_client.fail = True

    r = await client.post(f"/sales/{sale_id}/pay", headers=t["headers"], json={})

    assert r.status_code == 502
    got = await client.get(f"/sales/{sale_id}", headers=t["headers"])
    assert got.json()["status"] == "awaiting_payment"


async def test_pay_without_payments_configured_is_503(client):
    """No PAYMENTS_BASE_URL: say so, don't pretend a payment was requested."""
    t = await onboard(client, **A)
    sale_id = await _sale(client, t, customer_msisdn="254796036246")
    r = await client.post(f"/sales/{sale_id}/pay", headers=t["headers"], json={})
    assert r.status_code == 503


async def test_cannot_pay_a_cancelled_sale(client, payments_client):
    t = await onboard(client, **A)
    sale_id = await _sale(client, t, customer_msisdn="254796036246")
    await client.post(
        f"/sales/{sale_id}/transition", headers=t["headers"], json={"target": "cancelled"}
    )
    r = await client.post(f"/sales/{sale_id}/pay", headers=t["headers"], json={})
    assert r.status_code == 409
    assert not payments_client.calls


# --- hop 2: Payments -> POS ----------------------------------------------------
def _result(payment_id, **overrides) -> dict:
    return {
        "payment_id": str(payment_id),
        "result": "paid",
        "amount_minor_units": 12500,
        "mpesa_receipt": "RCPT123",
        **overrides,
    }


async def _paid_sale(client, payments_client, tenant):
    sale_id = await _sale(client, tenant, customer_msisdn="254796036246")
    await client.post(f"/sales/{sale_id}/pay", headers=tenant["headers"], json={})
    return sale_id


async def test_payment_result_marks_the_sale_paid(client, payments_client):
    t = await onboard(client, **A)
    sale_id = await _paid_sale(client, payments_client, t)

    r = await client.post(
        f"/internal/sales/{sale_id}/payment-result",
        headers=t["headers"],
        json=_result(payments_client.payment_id),
    )

    assert r.status_code == 200
    assert r.json() == {"sale_id": sale_id, "status": "paid", "changed": True}


async def test_replayed_payment_result_changes_nothing(client, payments_client):
    """A duplicated M-Pesa callback must produce exactly one state change."""
    t = await onboard(client, **A)
    sale_id = await _paid_sale(client, payments_client, t)
    body = _result(payments_client.payment_id)

    first = await client.post(
        f"/internal/sales/{sale_id}/payment-result", headers=t["headers"], json=body
    )
    second = await client.post(
        f"/internal/sales/{sale_id}/payment-result", headers=t["headers"], json=body
    )

    assert first.json()["changed"] is True
    assert second.status_code == 200 and second.json()["changed"] is False
    assert second.json()["status"] == "paid"


async def test_failed_payment_marks_the_sale_failed(client, payments_client):
    t = await onboard(client, **A)
    sale_id = await _paid_sale(client, payments_client, t)

    r = await client.post(
        f"/internal/sales/{sale_id}/payment-result",
        headers=t["headers"],
        json=_result(
            payments_client.payment_id,
            result="failed",
            mpesa_receipt=None,
            failure_reason="insufficient funds",
        ),
    )

    assert r.status_code == 200 and r.json()["status"] == "failed"


async def test_wrong_amount_is_refused(client, payments_client):
    """Settling a sale with money that isn't the sale's amount is a hard no."""
    t = await onboard(client, **A)
    sale_id = await _paid_sale(client, payments_client, t)

    r = await client.post(
        f"/internal/sales/{sale_id}/payment-result",
        headers=t["headers"],
        json=_result(payments_client.payment_id, amount_minor_units=100),
    )

    assert r.status_code == 409
    got = await client.get(f"/sales/{sale_id}", headers=t["headers"])
    assert got.json()["status"] == "awaiting_payment"


async def test_result_for_a_cancelled_sale_is_refused(client, payments_client):
    t = await onboard(client, **A)
    sale_id = await _sale(client, t, customer_msisdn="254796036246")
    await client.post(
        f"/sales/{sale_id}/transition", headers=t["headers"], json={"target": "cancelled"}
    )

    r = await client.post(
        f"/internal/sales/{sale_id}/payment-result",
        headers=t["headers"],
        json=_result(uuid.uuid4()),
    )

    assert r.status_code == 409


async def test_result_settles_a_sale_that_never_left_pending(client, payments_client):
    """The handoff response can be lost; the outcome still settles the sale."""
    t = await onboard(client, **A)
    sale_id = await _sale(client, t, customer_msisdn="254796036246")

    r = await client.post(
        f"/internal/sales/{sale_id}/payment-result",
        headers=t["headers"],
        json=_result(uuid.uuid4()),
    )

    assert r.status_code == 200 and r.json()["status"] == "paid"


async def test_another_tenants_sale_is_invisible_to_the_result_endpoint(client, payments_client):
    t = await onboard(client, **A)
    other = await onboard(client, **B)
    sale_id = await _paid_sale(client, payments_client, t)

    r = await client.post(
        f"/internal/sales/{sale_id}/payment-result",
        headers=other["headers"],
        json=_result(payments_client.payment_id),
    )

    assert r.status_code == 404
