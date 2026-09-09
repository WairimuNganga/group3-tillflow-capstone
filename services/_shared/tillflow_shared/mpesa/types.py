from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tillflow_shared.mpesa.scenarios import FakeScenario


class MpesaRequestBase(BaseModel):
    """Fields common to every adapter call."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str
    idempotency_key: str
    fake_scenario: FakeScenario | None = Field(
        default=None,
        description="Honoured only by FakeMpesaAdapter; ignored by DarajaSandboxAdapter.",
    )


class StkPushRequest(MpesaRequestBase):
    phone_number: str
    amount_whole_kes: int = Field(gt=0, description="Whole shillings — M-Pesa boundary.")
    account_reference: str
    transaction_desc: str = "TillFlow payment"


class StkPushResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    merchant_request_id: str
    checkout_request_id: str
    response_code: str
    response_description: str
    customer_message: str


class TransactionQueryRequest(MpesaRequestBase):
    checkout_request_id: str


class TransactionQueryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_code: str
    result_desc: str
    amount_whole_kes: int | None = None
    mpesa_receipt_number: str | None = None


class B2CRequest(MpesaRequestBase):
    phone_number: str
    amount_whole_kes: int = Field(gt=0)
    originator_conversation_id: str
    remarks: str = "TillFlow commission payout"


class B2CResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversation_id: str
    originator_conversation_id: str
    response_code: str
    response_description: str


class CallbackVerifyRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    callback_secret_segment: str
    expected_secret_segment: str
    payload: dict[str, Any]
    checkout_request_id: str
    amount_whole_kes: int | None = None


class CallbackVerifyResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    authentic: bool
    reason: str


class MpesaCallbackPayload(BaseModel):
    """Daraja STK callback body shape (stkCallback wrapper)."""

    model_config = ConfigDict(frozen=True)

    merchant_request_id: str
    checkout_request_id: str
    result_code: int
    result_desc: str
    amount_whole_kes: int | None = None
    mpesa_receipt_number: str | None = None

    def to_daraja_body(self) -> dict[str, Any]:
        metadata_items: list[dict[str, Any]] = []
        if self.amount_whole_kes is not None:
            metadata_items.append({"Name": "Amount", "Value": self.amount_whole_kes})
        if self.mpesa_receipt_number is not None:
            metadata_items.append({"Name": "MpesaReceiptNumber", "Value": self.mpesa_receipt_number})

        callback_metadata: dict[str, Any] = {"Item": metadata_items} if metadata_items else {"Item": []}
        return {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": self.merchant_request_id,
                    "CheckoutRequestID": self.checkout_request_id,
                    "ResultCode": self.result_code,
                    "ResultDesc": self.result_desc,
                    "CallbackMetadata": callback_metadata,
                }
            }
        }
