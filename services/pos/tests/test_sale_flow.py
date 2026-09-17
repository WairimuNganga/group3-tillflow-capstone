"""Sale lifecycle + idempotency + money, through the API in memory mode.

No database needed — proves service logic runs on the in-memory repository
(payments-style CI without Postgres). RLS is proved separately against Postgres
in test_rls_isolation.py.
"""

from tests.conftest import new_key, onboard, sale_payload

A = dict(name="A", phone="254700000001", shortcode="111111", att_phone="254711111111")
B = dict(name="B", phone="254700000002", shortcode="222222", att_phone="254722222222")


async def test_onboard_and_create_sale(client):
    t = await onboard(client, **A)
    headers = {**t["headers"], "Idempotency-Key": new_key()}
    r = await client.post("/sales", headers=headers, json=sale_payload(t))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["total_minor"] == 12500  # 3*2000 + 1*6500
    assert {i["name"]: i["line_total_minor"] for i in body["items"]} == {
        "Sukuma": 6000,
        "Bread": 6500,
    }


async def test_idempotent_replay_returns_same_sale(client):
    t = await onboard(client, **A)
    headers = {**t["headers"], "Idempotency-Key": "sale-key-1"}
    r1 = await client.post("/sales", headers=headers, json=sale_payload(t))
    r2 = await client.post("/sales", headers=headers, json=sale_payload(t))
    assert r1.status_code == 201 and r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]
    # replay didn't create a second sale
    listed = await client.get("/sales", headers=t["headers"])
    assert len(listed.json()) == 1


async def test_same_key_different_tenant_allowed(client):
    a = await onboard(client, **A)
    b = await onboard(client, **B)
    r1 = await client.post(
        "/sales", headers={**a["headers"], "Idempotency-Key": "shared"}, json=sale_payload(a)
    )
    r2 = await client.post(
        "/sales", headers={**b["headers"], "Idempotency-Key": "shared"}, json=sale_payload(b)
    )
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]


async def test_missing_idempotency_key_rejected(client):
    t = await onboard(client, **A)
    r = await client.post("/sales", headers=t["headers"], json=sale_payload(t))
    assert r.status_code == 400


async def test_missing_tenant_header_rejected(client):
    r = await client.get("/sales")
    assert r.status_code == 400


async def test_bad_till_rejected(client):
    import uuid

    t = await onboard(client, **A)
    headers = {**t["headers"], "Idempotency-Key": new_key()}
    payload = sale_payload(t, till_id=str(uuid.uuid4()))
    r = await client.post("/sales", headers=headers, json=payload)
    assert r.status_code == 400


async def test_full_flow_to_paid(client):
    t = await onboard(client, **A)
    headers = {**t["headers"], "Idempotency-Key": new_key()}
    sale_id = (await client.post("/sales", headers=headers, json=sale_payload(t))).json()["id"]

    async def transition(target):
        return await client.post(
            f"/sales/{sale_id}/transition", headers=t["headers"], json={"target": target}
        )

    assert (await transition("awaiting_payment")).json()["status"] == "awaiting_payment"
    assert (await transition("paid")).json()["status"] == "paid"


async def test_illegal_transition_409(client):
    t = await onboard(client, **A)
    headers = {**t["headers"], "Idempotency-Key": new_key()}
    sale_id = (await client.post("/sales", headers=headers, json=sale_payload(t))).json()["id"]
    r = await client.post(
        f"/sales/{sale_id}/transition", headers=t["headers"], json={"target": "paid"}
    )
    assert r.status_code == 409


async def test_same_state_transition_is_noop(client):
    t = await onboard(client, **A)
    headers = {**t["headers"], "Idempotency-Key": new_key()}
    sale_id = (await client.post("/sales", headers=headers, json=sale_payload(t))).json()["id"]
    await client.post(
        f"/sales/{sale_id}/transition", headers=t["headers"], json={"target": "awaiting_payment"}
    )
    r = await client.post(
        f"/sales/{sale_id}/transition", headers=t["headers"], json={"target": "awaiting_payment"}
    )
    assert r.status_code == 200 and r.json()["status"] == "awaiting_payment"


async def test_health(client):
    assert (await client.get("/health")).status_code == 200
