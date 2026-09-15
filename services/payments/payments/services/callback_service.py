from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from payments.domain.models import PaymentCallback
from payments.domain.state import PaymentState
from payments.repositories.memory import InMemoryPaymentRepository
from payments.repositories.memory_settlement import (
    InMemoryCallbackRepository,
    InMemoryLedgerRepository,
)
from payments.repositories.postgres import PostgresPaymentRepository
from payments.repositories.postgres_settlement import (
    PostgresCallbackRepository,
    PostgresLedgerRepository,
)
from payments.services.settlement import settle_failure, settle_success
from tillflow_shared.mpesa.adapter import MpesaAdapter
from tillflow_shared.mpesa.types import CallbackVerifyRequest
from tillflow_shared.otel import business_counter
from tillflow_shared.otel.middleware import traced

callback_processed = business_counter(
    "payments_callback_processed_total",
    "Daraja STK callbacks processed by result.",
)

PaymentRepository = InMemoryPaymentRepository | PostgresPaymentRepository
CallbackRepository = InMemoryCallbackRepository | PostgresCallbackRepository
LedgerRepository = InMemoryLedgerRepository | PostgresLedgerRepository


@dataclass(frozen=True)
class CallbackResult:
    accepted: bool
    reason: str
    payment_id: UUID | None = None
    state: str | None = None
    ledger_written: bool = False


class CallbackAuthError(Exception):
    """Callback secret segment did not match."""


class CallbackService:
    """Idempotent, order-independent STK callback settlement ([ADR-004])."""

    def __init__(
        self,
        *,
        payments: PaymentRepository,
        callbacks: CallbackRepository,
        ledger: LedgerRepository,
        adapter: MpesaAdapter,
        expected_callback_secret: str,
    ) -> None:
        self._payments = payments
        self._callbacks = callbacks
        self._ledger = ledger
        self._adapter = adapter
        self._expected_secret = expected_callback_secret

    async def handle(
        self,
        *,
        callback_secret: str,
        payload: dict[str, Any],
    ) -> CallbackResult:
        with traced("payments.callback_process"):
            return await self._handle(callback_secret=callback_secret, payload=payload)

    async def _handle(
        self,
        *,
        callback_secret: str,
        payload: dict[str, Any],
    ) -> CallbackResult:
        stk = _extract_stk_callback(payload)
        merchant_request_id = str(stk.get("MerchantRequestID", ""))
        checkout_request_id = str(stk.get("CheckoutRequestID", ""))
        result_code = int(stk.get("ResultCode", -1))
        amount_whole = _extract_amount_whole_kes(stk)
        receipt = _extract_receipt(stk)

        verify = await self._adapter.verify_callback_authenticity(
            CallbackVerifyRequest(
                tenant_id="callback",
                callback_secret_segment=callback_secret,
                expected_secret_segment=self._expected_secret,
                payload=payload,
                checkout_request_id=checkout_request_id,
                amount_whole_kes=amount_whole,
            )
        )
        if not verify.authentic:
            raise CallbackAuthError(verify.reason)

        payment = await self._payments.get_by_checkout_request_id(checkout_request_id)
        if payment is None:
            callback_processed.add(1, {"result": "unknown_payment"})
            return CallbackResult(accepted=True, reason="unknown_checkout_request_id")

        inserted = await self._callbacks.try_insert(
            PaymentCallback(
                tenant_id=payment.tenant_id,
                payment_id=payment.id,
                merchant_request_id=merchant_request_id or (payment.merchant_request_id or ""),
                checkout_request_id=checkout_request_id,
                result_code=result_code,
                raw_payload=payload,
                received_at=datetime.now(UTC),
            )
        )
        if not inserted:
            if result_code == 0 and payment.payment_state is not PaymentState.PAID:
                settled = await settle_success(
                    payments=self._payments,
                    ledger=self._ledger,
                    payment=payment,
                    amount_whole=amount_whole,
                    receipt=receipt,
                )
                callback_processed.add(1, {"result": settled.reason})
                return CallbackResult(
                    accepted=True,
                    reason=settled.reason,
                    payment_id=settled.payment.id,
                    state=settled.payment.state,
                    ledger_written=settled.ledger_written,
                )
            callback_processed.add(1, {"result": "duplicate"})
            return CallbackResult(
                accepted=True,
                reason="duplicate_callback",
                payment_id=payment.id,
                state=payment.state,
                ledger_written=False,
            )

        if result_code == 0:
            settled = await settle_success(
                payments=self._payments,
                ledger=self._ledger,
                payment=payment,
                amount_whole=amount_whole,
                receipt=receipt,
            )
        else:
            settled = await settle_failure(
                payments=self._payments,
                payment=payment,
                result_desc=stk.get("ResultDesc"),
            )

        callback_processed.add(1, {"result": settled.reason})
        return CallbackResult(
            accepted=True,
            reason=settled.reason,
            payment_id=settled.payment.id,
            state=settled.payment.state,
            ledger_written=settled.ledger_written,
        )


def _extract_stk_callback(payload: dict[str, Any]) -> dict[str, Any]:
    body = payload.get("Body") or payload
    if isinstance(body, dict) and "stkCallback" in body:
        return body["stkCallback"]
    if "stkCallback" in payload:
        return payload["stkCallback"]
    return payload


def _extract_amount_whole_kes(stk: dict[str, Any]) -> int | None:
    metadata = stk.get("CallbackMetadata") or {}
    items = metadata.get("Item") or []
    for item in items:
        if item.get("Name") == "Amount":
            value = item.get("Value")
            return int(value) if value is not None else None
    return None


def _extract_receipt(stk: dict[str, Any]) -> str | None:
    metadata = stk.get("CallbackMetadata") or {}
    items = metadata.get("Item") or []
    for item in items:
        if item.get("Name") == "MpesaReceiptNumber":
            value = item.get("Value")
            return str(value) if value is not None else None
    return None
