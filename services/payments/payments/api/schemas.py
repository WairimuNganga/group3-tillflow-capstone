from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from tillflow_shared.mpesa.scenarios import FakeScenario


class StkInitiateRequest(BaseModel):
    """POS → Payments STK handoff. Amounts are integer minor units ([ADR-004])."""

    model_config = ConfigDict(frozen=True)

    sale_id: UUID
    phone_number: str = Field(min_length=9, max_length=32)
    amount_minor_units: int = Field(gt=0)
    fake_scenario: FakeScenario | None = Field(
        default=None,
        description="Test-only; FakeMpesaAdapter scenarios. Ignored by sandbox.",
    )


class StkInitiateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    payment_id: UUID
    sale_id: UUID
    tenant_id: str
    state: str
    amount_minor_units: int
    amount_whole_kes: int
    merchant_request_id: str | None = None
    checkout_request_id: str | None = None


class B2CInitiateRequest(BaseModel):
    """Commission → Payments B2C handoff. Amounts are integer minor units."""

    model_config = ConfigDict(frozen=True)

    attendant_id: str = Field(min_length=1, max_length=128)
    phone_number: str = Field(min_length=9, max_length=32)
    amount_minor_units: int = Field(gt=0)
    originator_conversation_id: str = Field(
        min_length=1,
        max_length=128,
        description="Deterministic key, e.g. tenant:period:attendant",
    )


class B2CInitiateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    payout_id: UUID
    tenant_id: str
    attendant_id: str
    state: str
    amount_minor_units: int
    amount_whole_kes: int
    originator_conversation_id: str
    conversation_id: str | None = None


class B2CResultRequest(BaseModel):
    """Simplified ResultURL body for tests / sandbox mapping."""

    model_config = ConfigDict(frozen=True)

    conversation_id: str
    success: bool = True
    result_desc: str | None = None
