from fastapi.testclient import TestClient

from web.main import app


def test_health():
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "web"


def test_ready():
    client = TestClient(app)
    assert client.get("/ready").status_code == 200


def test_home_renders_brand_and_csp():
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "Till" in r.text
    assert "Flow" in r.text
    assert "Open a demo shop" in r.text
    assert "Content-Security-Policy" in r.headers
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


def test_setup_requires_csrf():
    client = TestClient(app)
    r = client.post(
        "/setup",
        data={
            "shop_name": "Shop",
            "owner_phone": "254700000001",
            "attendant_name": "A",
            "attendant_phone": "254711111111",
            "shortcode": "123456",
            "csrf_token": "wrong",
        },
    )
    assert r.status_code == 403


def test_setup_and_sale_flow_with_fake_pos():
    client = TestClient(app)
    home = client.get("/")
    assert home.status_code == 200
    csrf = home.cookies.get("tillflow_csrf")
    assert csrf

    setup = client.post(
        "/setup",
        data={
            "shop_name": "Mama Mboga",
            "owner_phone": "254700000001",
            "attendant_name": "Amina",
            "attendant_phone": "254712345678",
            "shortcode": "174379",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert setup.status_code == 303
    assert "tillflow_session" in setup.cookies

    # Refresh CSRF from cookie jar after redirect chain
    client.get("/")
    csrf = client.cookies.get("tillflow_csrf")

    sale_page = client.get("/sale")
    assert sale_page.status_code == 200
    assert "New sale" in sale_page.text

    created = client.post(
        "/sale",
        data={
            "item_name": "Shopping",
            "amount_kes": "145",
            "customer_phone": "254712345678",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert created.headers["location"].startswith("/sales/")

    status = client.get(created.headers["location"])
    assert status.status_code == 200
    assert "KES 145" in status.text
    assert "awaiting_payment" in status.text or "Sale status" in status.text

    listed = client.get("/sales")
    assert listed.status_code == 200
    assert "Shop sales" in listed.text
    assert "KES 145" in listed.text
    assert "Amina" in listed.text
    assert "awaiting_payment" in listed.text
    assert "2%" in listed.text
    assert "Commission" in listed.text
    assert "—" in listed.text

    filtered = client.get("/sales", params={"status": "paid"})
    assert filtered.status_code == 200
    assert "No sales match these filters." in filtered.text

    by_status = client.get("/sales", params={"status": "awaiting_payment"})
    assert by_status.status_code == 200
    assert "KES 145" in by_status.text
    assert "Page 1 of 1" in by_status.text
    assert "Showing 1–1 of 1" in by_status.text

    from web.deps import get_fake_pos

    fake = get_fake_pos()
    sale_id = created.headers["location"].rsplit("/", 1)[-1]
    fake.sales[sale_id].status = "paid"
    paid_list = client.get("/sales", params={"status": "paid"})
    assert paid_list.status_code == 200
    assert "KES 2.90" in paid_list.text  # 14500 * 200bps / 10000

    day = client.get("/commission", params={"period": "2026-09-20"})
    assert day.status_code == 200
    assert "Attendant day" in day.text
    assert "Amina" in day.text
    assert "Estimated commission" in day.text
    assert "2.90" in day.text
    assert "Close &amp; payout" in day.text or "Close & payout" in day.text

    from web.clients.commission import PayoutRow
    from web.deps import get_fake_commission, get_fake_pos

    fake = get_fake_pos()
    shop = next(iter(fake.shops.values()))
    get_fake_commission().payout_rows = [
        PayoutRow(
            tenant_id=shop.tenant_id,
            payout_period="2026-09-20",
            attendant_id=shop.attendant_id,
            phone_number="254712345678",
            amount_minor_units=290,
            state="submitted",
            payments_payout_id="payout-abc-123456",
            created_at="2026-09-20T12:00:00Z",
            updated_at="2026-09-20T12:05:00Z",
        )
    ]
    payouts_page = client.get("/payouts")
    assert payouts_page.status_code == 200
    assert "Payouts" in payouts_page.text
    assert "KES 2.90" in payouts_page.text
    assert "submitted" in payouts_page.text
    assert "Amina" in payouts_page.text
    assert "payout-a…" in payouts_page.text or "payout-abc" in payouts_page.text

    filtered_payouts = client.get("/payouts", params={"state": "pending"})
    assert filtered_payouts.status_code == 200
    assert "No payouts match these filters." in filtered_payouts.text

    # Seed enough sales to cross a page boundary (page size 10).
    for i in range(12):
        client.post(
            "/sale",
            data={
                "item_name": f"Item {i}",
                "amount_kes": str(100 + i),
                "customer_phone": "254712345678",
                "csrf_token": client.cookies.get("tillflow_csrf"),
            },
            follow_redirects=False,
        )
    page1 = client.get("/sales")
    assert page1.status_code == 200
    assert "Page 1 of 2" in page1.text
    page2 = client.get("/sales", params={"page": 2})
    assert page2.status_code == 200
    assert "Page 2 of 2" in page2.text
