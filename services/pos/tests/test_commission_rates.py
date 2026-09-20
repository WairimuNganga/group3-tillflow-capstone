"""POS commission rate API."""

from __future__ import annotations

from tests.conftest import onboard

A = dict(name="RateShop", phone="254700000010", shortcode="101010", att_phone="254711000010")


async def test_set_and_list_commission_rate(client):
    t = await onboard(client, **A)
    headers = t["headers"]

    created = await client.post(
        "/commission-rates",
        headers=headers,
        json={"attendant_id": t["attendant_id"], "rate_bps": 250},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["rate_bps"] == 250
    assert body["attendant_id"] == t["attendant_id"]

    listed = await client.get("/commission-rates", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
