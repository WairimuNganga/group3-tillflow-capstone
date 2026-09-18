"""POS -> Payments client for the STK handoff.

POS never talks to Daraja. It asks Payments to collect, and Payments reports the
outcome back through ``/internal/sales/{id}/payment-result`` ([ADR-004],
[ADR-007]). The idempotency key is derived from the sale id, so a retried
handoff reaches the same payment instead of prompting the customer twice.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

import httpx
from tillflow_shared.otel.http_client import AsyncServiceClient

STK_PATH = "/payments/stk"


class PaymentsUnavailableError(Exception):
    """Payments could not be reached, or refused the handoff."""


@dataclass(frozen=True)
class StkResult:
    payment_id: uuid.UUID | None
    state: str | None


def stk_idempotency_key(sale_id: uuid.UUID) -> str:
    """One STK request per sale, however many times the till retries."""
    return f"stk-{sale_id}"


class PaymentsClient(Protocol):
    async def initiate_stk(
        self,
        *,
        tenant_id: uuid.UUID,
        sale_id: uuid.UUID,
        phone_number: str,
        amount_minor_units: int,
    ) -> StkResult: ...


class HttpPaymentsClient:
    """Calls Payments over HTTP, carrying trace + tenant context."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def initiate_stk(
        self,
        *,
        tenant_id: uuid.UUID,
        sale_id: uuid.UUID,
        phone_number: str,
        amount_minor_units: int,
    ) -> StkResult:
        payload = {
            "sale_id": str(sale_id),
            "phone_number": phone_number,
            "amount_minor_units": amount_minor_units,
        }
        headers = {
            "X-Tenant-Id": str(tenant_id),
            "Idempotency-Key": stk_idempotency_key(sale_id),
        }
        try:
            async with AsyncServiceClient(service_name="pos", base_url=self._base_url) as client:
                response = await client.post(STK_PATH, json=payload, headers=headers)
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # The sale stays awaiting_payment: an unreachable Payments is an
            # uncertain payment, never a decline ([ADR-004]).
            raise PaymentsUnavailableError(str(exc)) from exc

        payment_id = body.get("payment_id")
        return StkResult(
            payment_id=uuid.UUID(payment_id) if payment_id else None,
            state=body.get("state"),
        )
