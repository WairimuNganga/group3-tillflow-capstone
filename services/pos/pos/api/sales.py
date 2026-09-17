"""Sales API: idempotent creation, reads, and the state machine."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from pos.api.schemas import CreateSaleRequest, SaleResponse, TransitionRequest
from pos.deps import get_sale_service, require_idempotency_key, require_tenant
from pos.domain.state import InvalidStateTransitionError
from pos.repositories.errors import InvalidReferenceError
from pos.services.sale_service import SaleLine, SaleService

router = APIRouter(tags=["sales"])

SaleServiceDep = Annotated[SaleService, Depends(get_sale_service)]
TenantId = Annotated[uuid.UUID, Depends(require_tenant)]
IdempotencyKey = Annotated[str, Depends(require_idempotency_key)]


@router.post("/sales", response_model=SaleResponse)
async def create_sale(
    body: CreateSaleRequest,
    response: Response,
    tenant_id: TenantId,
    idempotency_key: IdempotencyKey,
    service: SaleServiceDep,
) -> SaleResponse:
    """Idempotent on ``Idempotency-Key`` (scoped per tenant). Replaying the key
    returns the original sale as 200; a new sale is 201."""
    try:
        sale, created = await service.create(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            till_id=body.till_id,
            attendant_id=body.attendant_id,
            lines=[SaleLine(i.name, i.quantity, i.unit_price_minor) for i in body.items],
            currency=body.currency,
            customer_msisdn=body.customer_msisdn,
        )
    except InvalidReferenceError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "till_id or attendant_id does not belong to this tenant",
        ) from exc

    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return SaleResponse.model_validate(sale)


@router.get("/sales", response_model=list[SaleResponse])
async def list_sales(tenant_id: TenantId, service: SaleServiceDep) -> list[SaleResponse]:
    sales = await service.list(tenant_id=tenant_id)
    return [SaleResponse.model_validate(s) for s in sales]


@router.get("/sales/{sale_id}", response_model=SaleResponse)
async def get_sale(
    sale_id: uuid.UUID, tenant_id: TenantId, service: SaleServiceDep
) -> SaleResponse:
    sale = await service.get(tenant_id=tenant_id, sale_id=sale_id)
    if sale is None:
        # RLS also hides other tenants' sales, so a wrong tenant sees 404 too.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sale not found")
    return SaleResponse.model_validate(sale)


@router.post("/sales/{sale_id}/transition", response_model=SaleResponse)
async def transition_sale(
    sale_id: uuid.UUID,
    body: TransitionRequest,
    tenant_id: TenantId,
    service: SaleServiceDep,
) -> SaleResponse:
    try:
        sale = await service.transition(tenant_id=tenant_id, sale_id=sale_id, target=body.target)
    except InvalidStateTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if sale is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sale not found")
    return SaleResponse.model_validate(sale)
