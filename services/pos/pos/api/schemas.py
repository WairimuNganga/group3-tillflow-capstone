"""Request/response models. Money is always integer minor units (ADR-004)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

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


# --- payment handoff -----------------------------------------------------------
class PayRequest(BaseModel):
    """Ask Payments to collect. Defaults to the sale's ``customer_msisdn``."""

    phone_number: str | None = Field(default=None, max_length=32)


class PayResponse(BaseModel):
    sale_id: uuid.UUID
    status: SaleStatus
    amount_minor_units: int
    payment_id: uuid.UUID | None
    payment_state: str | None


class PaymentResultRequest(BaseModel):
    """What Payments reports once M-Pesa's outcome is known ([ADR-004])."""

    payment_id: uuid.UUID
    result: Literal["paid", "failed"]
    amount_minor_units: int | None = Field(default=None, ge=0)
    mpesa_receipt: str | None = Field(default=None, max_length=64)
    failure_reason: str | None = Field(default=None, max_length=500)
    occurred_at: datetime | None = None


class PaymentResultResponse(BaseModel):
    sale_id: uuid.UUID
    status: SaleStatus
    changed: bool
