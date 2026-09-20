"""Crown-jewel commission invariants."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from commission.clients.payments import PaymentsClientError
from commission.deps import (
    get_close_service,
    get_fake_payments,
    get_memory_attendants,
    get_memory_intents,
    get_memory_ledger,
    get_memory_paid_sales,
    get_memory_queue,
    get_memory_rates,
    get_payout_service,
    reset_runtime_state,
)
from commission.domain.state import PayoutIntentState, commission_minor, payout_idempotency_key
from commission.main import app
from commission.repositories.reads import AttendantContact, AttendantRate, PaidSaleRow
from commission.worker.loop import WorkerLoop


@pytest.fixture
def client():
    reset_runtime_state()
    with TestClient(app) as c:
        yield c
    reset_runtime_state()


def _seed_sale(
    *,
    tenant_id: str = "tenant-a",
    attendant_id: str = "attendant-1",
    amount: int = 10000,
    period: date | None = None,
    settled: bool = True,
    pos_total: int | None = None,
):
    period = period or date(2026, 9, 19)
    settled_at = datetime(period.year, period.month, period.day, 12, 0, tzinfo=UTC)
    sale_id = uuid4()
    payment_id = uuid4()
    if settled:
        get_memory_paid_sales().seed(
            PaidSaleRow(
                tenant_id=tenant_id,
                sale_id=sale_id,
                payment_id=payment_id,
                amount_minor_units=amount,
                settled_at=settled_at,
                attendant_id=attendant_id,
                pos_total_minor=pos_total if pos_total is not None else amount,
            )
        )
    get_memory_rates().seed(
        AttendantRate(
            tenant_id=tenant_id,
            attendant_id=attendant_id,
            rate_bps=200,
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    get_memory_attendants().seed(
        AttendantContact(
            tenant_id=tenant_id,
            attendant_id=attendant_id,
            phone_number="254712345678",
        )
    )
    return sale_id, period


@pytest.mark.asyncio
async def test_only_paid_settled_sales_generate_ledger():
    """Invariant 1: unpaid / unsettled rows never ledger."""
    period = date(2026, 9, 19)
    # Seed rate + attendant but no paid sale rows.
    get_memory_rates().seed(
        AttendantRate(
            tenant_id="tenant-a",
            attendant_id="attendant-1",
            rate_bps=200,
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    close = get_close_service(session=None)
    result = await close.run(period)
    assert result.ledger_lines_written == 0
    assert await get_memory_ledger().list_for_period(period) == []

    _seed_sale(period=period, amount=5000)
    result = await close.run(period)
    assert result.ledger_lines_written == 1
    lines = await get_memory_ledger().list_for_period(period)
    assert len(lines) == 1
    assert lines[0].commission_minor_units == commission_minor(5000, 200)


@pytest.mark.asyncio
async def test_close_twice_same_period_no_second_b2c():
    """Invariant 2: replay close → same ledger, no second B2C."""
    sale_id, period = _seed_sale(amount=10000)
    close = get_close_service(session=None)
    payout = get_payout_service(session=None)
    fake = get_fake_payments()

    first = await close.run(period)
    assert first.ledger_lines_written == 1
    assert first.intents_enqueued == 1

    # Drain and pay once.
    queue = get_memory_queue()
    msgs = await queue.receive(max_messages=10)
    assert len(msgs) == 1
    await payout.submit(
        tenant_id=msgs[0].body["tenant_id"],
        payout_period=date.fromisoformat(msgs[0].body["payout_period"]),
        attendant_id=msgs[0].body["attendant_id"],
    )
    assert len(fake.calls) == 1

    second = await close.run(period)
    assert second.already_completed is True
    assert second.ledger_lines_written == 0
    lines = await get_memory_ledger().list_for_period(period)
    assert len(lines) == 1
    assert lines[0].sale_id == sale_id

    # Replay close re-enqueues only if still pending — submitted should skip.
    assert second.intents_enqueued == 0
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_attendant_key_replay_one_b2c_call():
    """Invariant 3: same idempotency key → one Payments call result."""
    _, period = _seed_sale(amount=20000)
    close = get_close_service(session=None)
    payout = get_payout_service(session=None)
    fake = get_fake_payments()

    await close.run(period)
    key = payout_idempotency_key("tenant-a", period.isoformat(), "attendant-1")

    first = await payout.submit(
        tenant_id="tenant-a", payout_period=period, attendant_id="attendant-1"
    )
    second = await payout.submit(
        tenant_id="tenant-a", payout_period=period, attendant_id="attendant-1"
    )
    assert first.intent.payments_payout_id == second.intent.payments_payout_id
    assert first.already_requested is False
    assert second.already_requested is True
    assert second.next_payout_period == period + timedelta(days=1)
    assert len(fake.calls) == 1
    assert fake.calls[0]["idempotency_key"] == key
    total = await get_memory_ledger().sum_for_attendant("tenant-a", period, "attendant-1")
    assert total == commission_minor(20000, 200)


@pytest.mark.asyncio
async def test_mid_batch_resume_pays_only_failed():
    """Invariant 4: A completed, B fails → retry pays only B."""
    period = date(2026, 9, 19)
    for attendant, amount in (("attendant-a", 10000), ("attendant-b", 20000)):
        get_memory_paid_sales().seed(
            PaidSaleRow(
                tenant_id="tenant-a",
                sale_id=uuid4(),
                payment_id=uuid4(),
                amount_minor_units=amount,
                settled_at=datetime(2026, 9, 19, 10, 0, tzinfo=UTC),
                attendant_id=attendant,
                pos_total_minor=amount,
            )
        )
        get_memory_rates().seed(
            AttendantRate(
                tenant_id="tenant-a",
                attendant_id=attendant,
                rate_bps=200,
                effective_from=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        get_memory_attendants().seed(
            AttendantContact(
                tenant_id="tenant-a",
                attendant_id=attendant,
                phone_number="254700000001" if attendant.endswith("a") else "254700000002",
            )
        )

    close = get_close_service(session=None)
    payout = get_payout_service(session=None)
    fake = get_fake_payments()
    await close.run(period)

    await payout.submit(
        tenant_id="tenant-a", payout_period=period, attendant_id="attendant-a"
    )
    # Mark A completed so resume skips it.
    intent_a = await get_memory_intents().get("tenant-a", period, "attendant-a")
    assert intent_a is not None
    intent_a.state = PayoutIntentState.COMPLETED.value
    await get_memory_intents().upsert(intent_a)

    fake.fail_keys.add(payout_idempotency_key("tenant-a", period.isoformat(), "attendant-b"))
    with pytest.raises(PaymentsClientError):
        await payout.submit(
            tenant_id="tenant-a", payout_period=period, attendant_id="attendant-b"
        )
    assert len(fake.calls) == 2

    fake.fail_keys.clear()
    # Clear cached failure result so retry can succeed with new call.
    fake._results.pop(
        payout_idempotency_key("tenant-a", period.isoformat(), "attendant-b"), None
    )
    await payout.submit(
        tenant_id="tenant-a", payout_period=period, attendant_id="attendant-b"
    )
    # First A success + B fail attempt + B success = 3 calls; A not re-called on retry.
    assert len(fake.calls) == 3
    assert fake.calls[0]["attendant_id"] == "attendant-a"
    assert fake.calls[1]["attendant_id"] == "attendant-b"
    assert fake.calls[2]["attendant_id"] == "attendant-b"


@pytest.mark.asyncio
async def test_rate_change_does_not_reprice_ledgered_sales():
    """Invariant 5 (M9): later rate does not rewrite existing ledger lines."""
    period = date(2026, 9, 19)
    sale_id = uuid4()
    get_memory_paid_sales().seed(
        PaidSaleRow(
            tenant_id="tenant-a",
            sale_id=sale_id,
            payment_id=uuid4(),
            amount_minor_units=10000,
            settled_at=datetime(2026, 9, 19, 8, 0, tzinfo=UTC),
            attendant_id="attendant-1",
            pos_total_minor=10000,
        )
    )
    get_memory_rates().seed(
        AttendantRate(
            tenant_id="tenant-a",
            attendant_id="attendant-1",
            rate_bps=200,
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        AttendantRate(
            tenant_id="tenant-a",
            attendant_id="attendant-1",
            rate_bps=500,
            effective_from=datetime(2026, 9, 19, 18, 0, tzinfo=UTC),  # after period start
        ),
    )
    get_memory_attendants().seed(
        AttendantContact(
            tenant_id="tenant-a",
            attendant_id="attendant-1",
            phone_number="254712345678",
        )
    )

    close = get_close_service(session=None)
    await close.run(period)
    lines = await get_memory_ledger().list_for_period(period)
    assert len(lines) == 1
    assert lines[0].rate_bps == 200
    assert lines[0].commission_minor_units == commission_minor(10000, 200)

    # Mid-day higher rate must not reprice on replay.
    await close.run(period)
    lines = await get_memory_ledger().list_for_period(period)
    assert len(lines) == 1
    assert lines[0].rate_bps == 200


def test_no_daraja_import_in_commission_package():
    """Invariant 6: commission must not construct Daraja / mpesa adapters."""
    import importlib
    import pkgutil

    import commission

    forbidden = ("DarajaSandboxAdapter", "create_mpesa_adapter", "MpesaSettings")
    found: list[str] = []
    for mod in pkgutil.walk_packages(commission.__path__, commission.__name__ + "."):
        module = importlib.import_module(mod.name)
        src = getattr(module, "__file__", "") or ""
        if not src.endswith(".py"):
            continue
        with open(src, encoding="utf-8") as fh:
            text = fh.read()
        for token in forbidden:
            if token in text:
                found.append(f"{mod.name}:{token}")
    assert found == [], f"Daraja/mpesa leakage: {found}"


@pytest.mark.asyncio
async def test_worker_handles_daily_close_and_payout_events():
    _seed_sale(amount=10000)
    loop = WorkerLoop(
        queue=get_memory_queue(),
        close_service=get_close_service(session=None),
        payout_service=get_payout_service(session=None),
    )
    await loop.handle(
        {"event": "commission.daily_close.requested", "payout_period": "2026-09-19"}
    )
    msgs = await get_memory_queue().receive(max_messages=5)
    assert len(msgs) == 1
    await loop.handle(msgs[0].body)
    intent = await get_memory_intents().get("tenant-a", date(2026, 9, 19), "attendant-1")
    assert intent is not None
    assert intent.state in {
        PayoutIntentState.SUBMITTED.value,
        PayoutIntentState.COMPLETED.value,
    }


def test_internal_close_http(client: TestClient):
    _seed_sale(amount=10000, period=date(2026, 9, 19))
    response = client.post(
        "/internal/close",
        json={"payout_period": "2026-09-19"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ledger_lines_written"] == 1
    assert body["intents_enqueued"] == 1


def test_internal_summary_http(client: TestClient):
    _seed_sale(amount=10000, period=date(2026, 9, 19))
    client.post("/internal/close", json={"payout_period": "2026-09-19"})
    response = client.get(
        "/internal/summary",
        params={"payout_period": "2026-09-19", "tenant_id": "tenant-a"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["close_status"] == "completed"
    assert body["ledger_commission_minor_units"] > 0
    assert len(body["ledger_lines"]) == 1
    assert len(body["payout_intents"]) == 1


def test_internal_payouts_list_http(client: TestClient):
    _seed_sale(amount=10000, period=date(2026, 9, 19))
    client.post("/internal/close", json={"payout_period": "2026-09-19"})
    response = client.get("/internal/payouts", params={"tenant_id": "tenant-a"})
    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-a"
    assert len(body["payouts"]) == 1
    row = body["payouts"][0]
    assert row["payout_period"] == "2026-09-19"
    assert row["attendant_id"] == "attendant-1"
    assert row["amount_minor_units"] == 200
    assert row["state"] == "pending"

    filtered = client.get(
        "/internal/payouts",
        params={"tenant_id": "tenant-a", "state": "submitted"},
    )
    assert filtered.status_code == 200
    assert filtered.json()["payouts"] == []
