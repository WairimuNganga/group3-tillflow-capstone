import pytest

from tillflow_shared.mpesa.exceptions import MpesaTimeoutError
from tillflow_shared.mpesa.fake import FakeMpesaAdapter
from tillflow_shared.mpesa.scenarios import FakeScenario
from tillflow_shared.mpesa.types import (
    B2CRequest,
    CallbackVerifyRequest,
    StkPushRequest,
    TransactionQueryRequest,
)


@pytest.mark.asyncio
async def test_immediate_success(
    fake_adapter: FakeMpesaAdapter, sample_stk_request: StkPushRequest
) -> None:
    req = sample_stk_request.model_copy(update={"fake_scenario": FakeScenario.IMMEDIATE_SUCCESS})
    response = await fake_adapter.initiate_stk_push(req)

    assert response.response_code == "0"
    callbacks = fake_adapter.drain_callbacks(response.checkout_request_id)
    assert len(callbacks) == 1
    assert callbacks[0].result_code == 0

    query = await fake_adapter.query_transaction_status(
        TransactionQueryRequest(
            tenant_id=req.tenant_id,
            idempotency_key=req.idempotency_key,
            checkout_request_id=response.checkout_request_id,
        )
    )
    assert query.result_code == "0"
    assert query.amount_whole_kes == 10


@pytest.mark.asyncio
async def test_immediate_failure(
    fake_adapter: FakeMpesaAdapter, sample_stk_request: StkPushRequest
) -> None:
    req = sample_stk_request.model_copy(update={"fake_scenario": FakeScenario.IMMEDIATE_FAILURE})
    response = await fake_adapter.initiate_stk_push(req)

    callbacks = fake_adapter.drain_callbacks(response.checkout_request_id)
    assert len(callbacks) == 1
    assert callbacks[0].result_code == 1

    query = await fake_adapter.query_transaction_status(
        TransactionQueryRequest(
            tenant_id=req.tenant_id,
            idempotency_key=req.idempotency_key,
            checkout_request_id=response.checkout_request_id,
        )
    )
    assert query.result_code == "1"


@pytest.mark.asyncio
async def test_delayed_timeout(
    fake_adapter: FakeMpesaAdapter, sample_stk_request: StkPushRequest
) -> None:
    req = sample_stk_request.model_copy(update={"fake_scenario": FakeScenario.DELAYED_TIMEOUT})

    with pytest.raises(MpesaTimeoutError):
        await fake_adapter.initiate_stk_push(req)


@pytest.mark.asyncio
async def test_duplicate_callback(
    fake_adapter: FakeMpesaAdapter, sample_stk_request: StkPushRequest
) -> None:
    req = sample_stk_request.model_copy(update={"fake_scenario": FakeScenario.DUPLICATE_CALLBACK})
    response = await fake_adapter.initiate_stk_push(req)

    callbacks = fake_adapter.drain_callbacks(response.checkout_request_id)
    assert len(callbacks) == 2
    assert callbacks[0].model_dump() == callbacks[1].model_dump()


@pytest.mark.asyncio
async def test_out_of_order_callback(
    fake_adapter: FakeMpesaAdapter, sample_stk_request: StkPushRequest
) -> None:
    req = sample_stk_request.model_copy(
        update={"fake_scenario": FakeScenario.OUT_OF_ORDER_CALLBACK}
    )
    response = await fake_adapter.initiate_stk_push(req)

    callbacks = fake_adapter.drain_callbacks(response.checkout_request_id)
    assert len(callbacks) == 2
    assert callbacks[0].result_code == 1
    assert callbacks[1].result_code == 0

    query = await fake_adapter.query_transaction_status(
        TransactionQueryRequest(
            tenant_id=req.tenant_id,
            idempotency_key=req.idempotency_key,
            checkout_request_id=response.checkout_request_id,
        )
    )
    assert query.result_code == "0"


@pytest.mark.asyncio
async def test_b2c_idempotent_by_originator_conversation_id(
    fake_adapter: FakeMpesaAdapter,
) -> None:
    req = B2CRequest(
        tenant_id="tenant-1",
        idempotency_key="payout-1",
        phone_number="254712345678",
        amount_whole_kes=50,
        originator_conversation_id="tenant-1:2026-09-01:att-7",
    )
    first = await fake_adapter.initiate_b2c(req)
    second = await fake_adapter.initiate_b2c(req)

    assert first.conversation_id == second.conversation_id
    assert first.originator_conversation_id == second.originator_conversation_id


@pytest.mark.asyncio
async def test_verify_callback_authenticity(fake_adapter: FakeMpesaAdapter) -> None:
    ok = await fake_adapter.verify_callback_authenticity(
        CallbackVerifyRequest(
            tenant_id="tenant-1",
            callback_secret_segment="secret-a",
            expected_secret_segment="secret-a",
            payload={},
            checkout_request_id="checkout-1",
        )
    )
    bad = await fake_adapter.verify_callback_authenticity(
        CallbackVerifyRequest(
            tenant_id="tenant-1",
            callback_secret_segment="secret-a",
            expected_secret_segment="secret-b",
            payload={},
            checkout_request_id="checkout-1",
        )
    )

    assert ok.authentic is True
    assert bad.authentic is False
