from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from starlette import status

from payments.api.schemas import StkInitiateRequest, StkInitiateResponse
from payments.deps import get_idempotency_handle, get_stk_service
from payments.domain.models import Payment
from payments.services.stk_service import StkService, StkValidationError
from tillflow_shared.idempotency import IdempotencyHandle

router = APIRouter(prefix="/payments", tags=["payments"])


def _to_response(payment: Payment) -> dict:
    return StkInitiateResponse(
        payment_id=payment.id,
        sale_id=payment.sale_id,
        tenant_id=payment.tenant_id,
        state=payment.state,
        amount_minor_units=payment.amount_minor_units,
        amount_whole_kes=payment.amount_whole_kes,
        merchant_request_id=payment.merchant_request_id,
        checkout_request_id=payment.checkout_request_id,
    ).model_dump(mode="json")


@router.post("/stk")
async def initiate_stk(
    body: StkInitiateRequest,
    handle: IdempotencyHandle = Depends(get_idempotency_handle),
    service: StkService = Depends(get_stk_service),
) -> JSONResponse:
    """Initiate STK Push for a POS sale.

    ``AccountReference`` on Daraja is the idempotency key. A timeout leaves the
    payment in ``pending_reconciliation`` (never declined).
    """
    await handle.begin()

    try:
        payment, status_code = await service.initiate(
            tenant_id=handle.tenant_id,
            idempotency_key=handle.key,
            sale_id=body.sale_id,
            phone_number=body.phone_number,
            amount_minor_units=body.amount_minor_units,
            fake_scenario=body.fake_scenario,
        )
    except StkValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    response_body = _to_response(payment)
    await handle.complete(status_code=status_code, response_body=response_body)
    return JSONResponse(status_code=status_code, content=response_body)
