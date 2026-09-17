"""Request/response models. Money is always integer minor units (ADR-004)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from pos.domain.state import SaleStatus


# --- tenant onboarding ---------------------------------------------------------
class CreateTenantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    owner_phone: str = Field(min_length=1, max_length=32)
    owner_name: str = Field(min_length=1, max_length=200)


class CreateTillRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    shortcode: str = Field(min_length=1, max_length=32)


class CreateAttendantRequest(BaseModel):
    phone: str = Field(min_length=1, max_length=32)
    display_name: str = Field(min_length=1, max_length=200)


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    status: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    phone: str
    display_name: str
    role: str
    status: str


class TillResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    shortcode: str
    status: str


class OnboardTenantResponse(BaseModel):
    tenant: TenantResponse
    owner: UserResponse


# --- sales ---------------------------------------------------------------------
class SaleItemInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(gt=0)
    unit_price_minor: int = Field(ge=0)


class CreateSaleRequest(BaseModel):
    till_id: uuid.UUID
    attendant_id: uuid.UUID
    items: list[SaleItemInput] = Field(min_length=1)
    customer_msisdn: str | None = Field(default=None, max_length=32)
    currency: str = Field(default="KES", min_length=3, max_length=3)


class SaleItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    quantity: int
    unit_price_minor: int
    line_total_minor: int


class SaleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    till_id: uuid.UUID
    attendant_id: uuid.UUID
    status: SaleStatus
    currency: str
    total_minor: int
    customer_msisdn: str | None
    items: list[SaleItemResponse]
    created_at: datetime


class TransitionRequest(BaseModel):
    target: SaleStatus
