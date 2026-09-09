from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

from tillflow_shared.mpesa.exceptions import MpesaTimeoutError
from tillflow_shared.mpesa.scenarios import FakeScenario
from tillflow_shared.mpesa.settings import MpesaSettings
from tillflow_shared.mpesa.types import (
    B2CRequest,
    B2CResponse,
    CallbackVerifyRequest,
    CallbackVerifyResult,
    MpesaCallbackPayload,
    StkPushRequest,
    StkPushResponse,
    TransactionQueryRequest,
    TransactionQueryResponse,
)


@dataclass
class _StkRecord:
    merchant_request_id: str
    checkout_request_id: str
    amount_whole_kes: int
    scenario: FakeScenario
    settled: bool = False
    final_result_code: str | None = None
    mpesa_receipt_number: str | None = None
    callbacks: list[MpesaCallbackPayload] = field(default_factory=list)


@dataclass
class _B2CRecord:
    conversation_id: str
    originator_conversation_id: str
    amount_whole_kes: int
    response_code: str


class FakeMpesaAdapter:
    """Deterministic in-memory M-Pesa double for CI, k6, and drills ([ADR-007])."""

    def __init__(self, settings: MpesaSettings, *, default_scenario: FakeScenario = FakeScenario.IMMEDIATE_SUCCESS) -> None:
        self._settings = settings
        self._default_scenario = default_scenario
        self._stk_records: dict[str, _StkRecord] = {}
        self._b2c_records: dict[str, _B2CRecord] = {}

    def drain_callbacks(self, checkout_request_id: str) -> list[MpesaCallbackPayload]:
        """Return queued callbacks for a checkout ID (tests simulate HTTP delivery)."""
        record = self._stk_records.get(checkout_request_id)
        if record is None:
            return []
        callbacks = list(record.callbacks)
        record.callbacks.clear()
        return callbacks

    async def initiate_stk_push(self, req: StkPushRequest) -> StkPushResponse:
        scenario = req.fake_scenario or self._default_scenario

        if scenario is FakeScenario.DELAYED_TIMEOUT:
            await asyncio.sleep(self._settings.http_read_timeout_seconds + 0.1)
            raise MpesaTimeoutError("simulated Daraja timeout")

        merchant_request_id = f"fake-merchant-{uuid.uuid4().hex[:12]}"
        checkout_request_id = f"fake-checkout-{uuid.uuid4().hex[:12]}"

        record = _StkRecord(
            merchant_request_id=merchant_request_id,
            checkout_request_id=checkout_request_id,
            amount_whole_kes=req.amount_whole_kes,
            scenario=scenario,
        )
        self._stk_records[checkout_request_id] = record

        if scenario is FakeScenario.IMMEDIATE_FAILURE:
            record.final_result_code = "1"
            record.callbacks.append(
                MpesaCallbackPayload(
                    merchant_request_id=merchant_request_id,
                    checkout_request_id=checkout_request_id,
                    result_code=1,
                    result_desc="The service request is failed.",
                )
            )
            return StkPushResponse(
                merchant_request_id=merchant_request_id,
                checkout_request_id=checkout_request_id,
                response_code="0",
                response_description="Accept the service request successfully.",
                customer_message="Success. Request accepted for processing",
            )

        if scenario is FakeScenario.IMMEDIATE_SUCCESS:
            receipt = f"FAKE{uuid.uuid4().hex[:8].upper()}"
            record.final_result_code = "0"
            record.settled = True
            record.mpesa_receipt_number = receipt
            record.callbacks.append(
                MpesaCallbackPayload(
                    merchant_request_id=merchant_request_id,
                    checkout_request_id=checkout_request_id,
                    result_code=0,
                    result_desc="The service request is processed successfully.",
                    amount_whole_kes=req.amount_whole_kes,
                    mpesa_receipt_number=receipt,
                )
            )
            return StkPushResponse(
                merchant_request_id=merchant_request_id,
                checkout_request_id=checkout_request_id,
                response_code="0",
                response_description="Success. Request accepted for processing",
                customer_message="Success. Request accepted for processing",
            )

        if scenario is FakeScenario.DUPLICATE_CALLBACK:
            receipt = f"FAKE{uuid.uuid4().hex[:8].upper()}"
            callback = MpesaCallbackPayload(
                merchant_request_id=merchant_request_id,
                checkout_request_id=checkout_request_id,
                result_code=0,
                result_desc="The service request is processed successfully.",
                amount_whole_kes=req.amount_whole_kes,
                mpesa_receipt_number=receipt,
            )
            record.final_result_code = "0"
            record.settled = True
            record.mpesa_receipt_number = receipt
            record.callbacks.extend([callback, callback])
            return StkPushResponse(
                merchant_request_id=merchant_request_id,
                checkout_request_id=checkout_request_id,
                response_code="0",
                response_description="Success. Request accepted for processing",
                customer_message="Success. Request accepted for processing",
            )

        if scenario is FakeScenario.OUT_OF_ORDER_CALLBACK:
            failure = MpesaCallbackPayload(
                merchant_request_id=merchant_request_id,
                checkout_request_id=checkout_request_id,
                result_code=1,
                result_desc="The service request is failed.",
            )
            receipt = f"FAKE{uuid.uuid4().hex[:8].upper()}"
            success = MpesaCallbackPayload(
                merchant_request_id=merchant_request_id,
                checkout_request_id=checkout_request_id,
                result_code=0,
                result_desc="The service request is processed successfully.",
                amount_whole_kes=req.amount_whole_kes,
                mpesa_receipt_number=receipt,
            )
            record.callbacks.extend([failure, success])
            record.final_result_code = "0"
            record.settled = True
            record.mpesa_receipt_number = receipt
            return StkPushResponse(
                merchant_request_id=merchant_request_id,
                checkout_request_id=checkout_request_id,
                response_code="0",
                response_description="Success. Request accepted for processing",
                customer_message="Success. Request accepted for processing",
            )

        raise ValueError(f"unsupported fake scenario: {scenario}")

    async def query_transaction_status(
        self, req: TransactionQueryRequest
    ) -> TransactionQueryResponse:
        record = self._stk_records.get(req.checkout_request_id)
        if record is None:
            return TransactionQueryResponse(
                result_code="1032",
                result_desc="Request cancelled by user",
            )

        if record.final_result_code == "0":
            return TransactionQueryResponse(
                result_code="0",
                result_desc="The service request is processed successfully.",
                amount_whole_kes=record.amount_whole_kes,
                mpesa_receipt_number=record.mpesa_receipt_number,
            )

        return TransactionQueryResponse(
            result_code=record.final_result_code or "1",
            result_desc="The service request is failed.",
        )

    async def initiate_b2c(self, req: B2CRequest) -> B2CResponse:
        if req.originator_conversation_id in self._b2c_records:
            existing = self._b2c_records[req.originator_conversation_id]
            return B2CResponse(
                conversation_id=existing.conversation_id,
                originator_conversation_id=existing.originator_conversation_id,
                response_code=existing.response_code,
                response_description="Duplicate payout request accepted (idempotent).",
            )

        conversation_id = f"fake-b2c-{uuid.uuid4().hex[:12]}"
        self._b2c_records[req.originator_conversation_id] = _B2CRecord(
            conversation_id=conversation_id,
            originator_conversation_id=req.originator_conversation_id,
            amount_whole_kes=req.amount_whole_kes,
            response_code="0",
        )
        return B2CResponse(
            conversation_id=conversation_id,
            originator_conversation_id=req.originator_conversation_id,
            response_code="0",
            response_description="Accept the service request successfully.",
        )

    async def verify_callback_authenticity(
        self, req: CallbackVerifyRequest
    ) -> CallbackVerifyResult:
        if req.callback_secret_segment != req.expected_secret_segment:
            return CallbackVerifyResult(
                authentic=False,
                reason="callback secret segment mismatch",
            )
        return CallbackVerifyResult(authentic=True, reason="secret segment matched")
