"""Internal endpoints — called by other TillFlow services, never by the public.

`/internal/*` is not routed from the API Gateway / ALB; only in-VPC callers
(Payments, over Service Connect) reach it. That boundary is what makes "a sale
is paid only when money moved" a permission, not a promise.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from pos.api.schemas import PaymentResultRequest, PaymentResultResponse
from pos.deps import get_sale_service, require_tenant
from pos.domain.state import InvalidStateTransitionError, SaleStatus
from pos.services.sale_service import AmountMismatchError, SaleService

router = APIRouter(prefix="/internal", tags=["internal"])

SaleServiceDep = Annotated[SaleService, Depends(get_sale_service)]
TenantId = Annotated[uuid.UUID, Depends(require_tenant)]


@router.post("/sales/{sale_id}/payment-result", response_model=PaymentResultResponse)
async def payment_result(
    sale_id: uuid.UUID,
    body: PaymentResultRequest,
    tenant_id: TenantId,
    service: SaleServiceDep,
) -> PaymentResultResponse:
    """Payments reports the M-Pesa outcome for a sale.

    Idempotent and order-independent: a replayed callback returns
    ``changed=false`` and leaves one state change and one set of payment
    references ([ADR-004]).
    """
    target = SaleStatus.PAID if body.result == "paid" else SaleStatus.FAILED
    try:
        outcome = await service.apply_payment_result(
            tenant_id=tenant_id,
            sale_id=sale_id,
            result=target,
            payment_id=body.payment_id,
            amount_minor_units=body.amount_minor_units,
            mpesa_receipt=body.mpesa_receipt,
        )
    except AmountMismatchError as exc:
        # Never settle a sale with money that isn't the sale's amount.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except InvalidStateTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    if outcome is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sale not found")

    sale, changed = outcome
    return PaymentResultResponse(sale_id=sale.id, status=sale.sale_status, changed=changed)
