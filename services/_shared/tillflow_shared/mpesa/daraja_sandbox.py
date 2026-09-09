from __future__ import annotations

import base64
from datetime import datetime, timezone

import httpx

from tillflow_shared.mpesa.exceptions import MpesaAuthError, MpesaProviderError, MpesaTimeoutError
from tillflow_shared.mpesa.oauth import OAuthTokenCache
from tillflow_shared.mpesa.settings import MpesaSettings
from tillflow_shared.mpesa.types import (
    B2CRequest,
    B2CResponse,
    CallbackVerifyRequest,
    CallbackVerifyResult,
    StkPushRequest,
    StkPushResponse,
    TransactionQueryRequest,
    TransactionQueryResponse,
)


class DarajaSandboxAdapter:
    """Real HTTP adapter for Safaricom Daraja sandbox ([ADR-007])."""

    def __init__(self, settings: MpesaSettings) -> None:
        self._settings = settings
        self._token_cache = OAuthTokenCache(settings)
        self._timeout = httpx.Timeout(
            connect=settings.http_connect_timeout_seconds,
            read=settings.http_read_timeout_seconds,
            write=settings.http_read_timeout_seconds,
            pool=settings.http_connect_timeout_seconds,
        )

    def _require_sandbox_config(self) -> None:
        missing = [
            name
            for name, value in {
                "DARAJA_CONSUMER_KEY": self._settings.daraja_consumer_key,
                "DARAJA_CONSUMER_SECRET": self._settings.daraja_consumer_secret,
                "DARAJA_PASSKEY": self._settings.daraja_passkey,
                "DARAJA_SHORTCODE": self._settings.daraja_shortcode,
            }.items()
            if not value
        ]
        if missing:
            raise MpesaAuthError(f"Daraja sandbox config missing: {', '.join(missing)}")

    async def _post(self, path: str, payload: dict) -> httpx.Response:
        self._require_sandbox_config()
        async with httpx.AsyncClient(
            base_url=self._settings.daraja_base_url,
            timeout=self._timeout,
        ) as client:
            token = await self._token_cache.get_access_token(client)
            try:
                return await client.post(
                    path,
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.TimeoutException as exc:
                raise MpesaTimeoutError(f"Daraja request timed out: {path}") from exc

    @staticmethod
    def _build_stk_password(shortcode: str, passkey: str, timestamp: str) -> str:
        raw = f"{shortcode}{passkey}{timestamp}"
        return base64.b64encode(raw.encode("utf-8")).decode("utf-8")

    async def initiate_stk_push(self, req: StkPushRequest) -> StkPushResponse:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        payload = {
            "BusinessShortCode": self._settings.daraja_shortcode,
            "Password": self._build_stk_password(
                self._settings.daraja_shortcode,
                self._settings.daraja_passkey,
                timestamp,
            ),
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": req.amount_whole_kes,
            "PartyA": req.phone_number,
            "PartyB": self._settings.daraja_shortcode,
            "PhoneNumber": req.phone_number,
            "CallBackURL": self._settings.daraja_stk_callback_url,
            "AccountReference": req.account_reference,
            "TransactionDesc": req.transaction_desc,
        }

        response = await self._post("/mpesa/stkpush/v1/processrequest", payload)
        if response.status_code >= 500:
            raise MpesaProviderError(f"Daraja STK push failed with status {response.status_code}")

        body = response.json()
        return StkPushResponse(
            merchant_request_id=body.get("MerchantRequestID", ""),
            checkout_request_id=body.get("CheckoutRequestID", ""),
            response_code=str(body.get("ResponseCode", "")),
            response_description=str(body.get("ResponseDescription", "")),
            customer_message=str(body.get("CustomerMessage", "")),
        )

    async def query_transaction_status(
        self, req: TransactionQueryRequest
    ) -> TransactionQueryResponse:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        payload = {
            "BusinessShortCode": self._settings.daraja_shortcode,
            "Password": self._build_stk_password(
                self._settings.daraja_shortcode,
                self._settings.daraja_passkey,
                timestamp,
            ),
            "Timestamp": timestamp,
            "CheckoutRequestID": req.checkout_request_id,
        }

        response = await self._post("/mpesa/stkpushquery/v1/query", payload)
        body = response.json()
        return TransactionQueryResponse(
            result_code=str(body.get("ResultCode", "")),
            result_desc=str(body.get("ResultDesc", "")),
        )

    async def initiate_b2c(self, req: B2CRequest) -> B2CResponse:
        if not self._settings.daraja_initiator or not self._settings.daraja_security_credential:
            raise MpesaAuthError("Daraja B2C config missing initiator or security credential")

        payload = {
            "InitiatorName": self._settings.daraja_initiator,
            "SecurityCredential": self._settings.daraja_security_credential,
            "CommandID": "BusinessPayment",
            "Amount": req.amount_whole_kes,
            "PartyA": self._settings.daraja_shortcode,
            "PartyB": req.phone_number,
            "Remarks": req.remarks,
            "QueueTimeOutURL": self._settings.daraja_b2c_result_url,
            "ResultURL": self._settings.daraja_b2c_result_url,
            "Occasion": "Commission",
            "OriginatorConversationID": req.originator_conversation_id,
        }

        response = await self._post("/mpesa/b2c/v1/paymentrequest", payload)
        body = response.json()
        return B2CResponse(
            conversation_id=str(body.get("ConversationID", "")),
            originator_conversation_id=str(body.get("OriginatorConversationID", "")),
            response_code=str(body.get("ResponseCode", "")),
            response_description=str(body.get("ResponseDescription", "")),
        )

    async def verify_callback_authenticity(
        self, req: CallbackVerifyRequest
    ) -> CallbackVerifyResult:
        if req.callback_secret_segment != req.expected_secret_segment:
            return CallbackVerifyResult(
                authentic=False,
                reason="callback secret segment mismatch",
            )
        return CallbackVerifyResult(
            authentic=True,
            reason="secret segment matched; re-query for high-value settlement",
        )
