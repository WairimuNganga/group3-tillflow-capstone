from typing import Protocol

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


class MpesaAdapter(Protocol):
    """Cross-team contract for all Daraja interactions ([ADR-007])."""

    async def initiate_stk_push(self, req: StkPushRequest) -> StkPushResponse: ...

    async def query_transaction_status(
        self, req: TransactionQueryRequest
    ) -> TransactionQueryResponse: ...

    async def initiate_b2c(self, req: B2CRequest) -> B2CResponse: ...

    async def verify_callback_authenticity(
        self, req: CallbackVerifyRequest
    ) -> CallbackVerifyResult: ...
