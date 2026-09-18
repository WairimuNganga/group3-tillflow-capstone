"""Tenant onboarding API: create a tenant + owner, add tills and attendants."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from pos.api.schemas import (
    CreateAttendantRequest,
    CreateTenantRequest,
    CreateTillRequest,
    OnboardTenantResponse,
    TenantResponse,
    TillResponse,
    UserResponse,
)
from pos.deps import get_tenant_service, require_tenant
from pos.repositories.errors import AlreadyExistsError
from pos.services.tenant_service import TenantService

router = APIRouter(tags=["tenants"])

TenantServiceDep = Annotated[TenantService, Depends(get_tenant_service)]
TenantId = Annotated[uuid.UUID, Depends(require_tenant)]


@router.post("/tenants", status_code=status.HTTP_201_CREATED, response_model=OnboardTenantResponse)
async def create_tenant(
    body: CreateTenantRequest, service: TenantServiceDep
) -> OnboardTenantResponse:
    try:
        tenant, owner = await service.onboard(
            name=body.name, owner_phone=body.owner_phone, owner_name=body.owner_name
        )
    except AlreadyExistsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "owner phone already exists") from exc
    return OnboardTenantResponse(
        tenant=TenantResponse.model_validate(tenant),
        owner=UserResponse.model_validate(owner),
    )


@router.post("/tills", status_code=status.HTTP_201_CREATED, response_model=TillResponse)
async def create_till(
    body: CreateTillRequest, tenant_id: TenantId, service: TenantServiceDep
) -> TillResponse:
    try:
        till = await service.add_till(tenant_id=tenant_id, name=body.name, shortcode=body.shortcode)
    except AlreadyExistsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "shortcode already exists") from exc
    return TillResponse.model_validate(till)


@router.post("/attendants", status_code=status.HTTP_201_CREATED, response_model=UserResponse)
async def create_attendant(
    body: CreateAttendantRequest, tenant_id: TenantId, service: TenantServiceDep
) -> UserResponse:
    try:
        user = await service.add_attendant(
            tenant_id=tenant_id, phone=body.phone, display_name=body.display_name
        )
    except AlreadyExistsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "phone already exists") from exc
    return UserResponse.model_validate(user)
