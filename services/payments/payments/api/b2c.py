from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from starlette import status
from tillflow_shared.idempotency import IdempotencyHandle

from payments.api.schemas import B2CInitiateRequest, B2CInitiateResponse, B2CResultRequest
from payments.deps import get_b2c_service, get_idempotency_handle
from payments.domain.models import Payout
from payments.services.b2c_service import B2CService, B2CValidationError

router = APIRouter(prefix="/payments", tags=["b2c"])


def _to_response(payout: Payout) -> dict:
    return B2CInitiateResponse(
        payout_id=payout.id,
        tenant_id=payout.tenant_id,
        attendant_id=payout.attendant_id,
        state=payout.state,
        amount_minor_units=payout.amount_minor_units,
        amount_whole_kes=payout.amount_whole_kes,
        originator_conversation_id=payout.originator_conversation_id,
        conversation_id=payout.conversation_id,
    ).model_dump(mode="json")


@router.post("/b2c")
async def initiate_b2c(
    body: B2CInitiateRequest,
    handle: IdempotencyHandle = Depends(get_idempotency_handle),
    service: B2CService = Depends(get_b2c_service),
) -> JSONResponse:
    """Initiate B2C payout for Commission.

    ``Idempotency-Key`` must equal ``originator_conversation_id``. Commission must
    never call Daraja directly — only this endpoint.
    """
    await handle.begin()

    try:
        payout, status_code = await service.initiate(
            tenant_id=handle.tenant_id,
            idempotency_key=handle.key,
            attendant_id=body.attendant_id,
            phone_number=body.phone_number,
            amount_minor_units=body.amount_minor_units,
            originator_conversation_id=body.originator_conversation_id,
        )
    except B2CValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    response_body = _to_response(payout)
    await handle.complete(status_code=status_code, response_body=response_body)
    return JSONResponse(status_code=status_code, content=response_body)


@router.post("/b2c/result")
async def b2c_result(
    body: B2CResultRequest,
    service: B2CService = Depends(get_b2c_service),
) -> JSONResponse:
    """Apply B2C ResultURL outcome (completed / failed). Idempotent on replay."""
    try:
        payout = await service.apply_result(
            conversation_id=body.conversation_id,
            success=body.success,
            result_desc=body.result_desc,
        )
    except B2CValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return JSONResponse(status_code=200, content=_to_response(payout))
