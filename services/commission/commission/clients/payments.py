from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from tillflow_shared.otel.http_client import AsyncServiceClient


class PaymentsClientError(RuntimeError):
    """Payments B2C call failed."""


@dataclass(frozen=True, slots=True)
class B2CResult:
    payout_id: UUID
    state: str
    amount_minor_units: int
    conversation_id: str | None


class PaymentsClient:
    """Commission → Payments B2C only — never Daraja."""

    def __init__(self, base_url: str) -> None:
        if not base_url:
            raise ValueError("PAYMENTS_BASE_URL is required for B2C")
        self._base_url = base_url.rstrip("/")

    async def initiate_b2c(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        attendant_id: str,
        phone_number: str,
        amount_minor_units: int,
    ) -> B2CResult:
        payload: dict[str, Any] = {
            "attendant_id": attendant_id,
            "phone_number": phone_number,
            "amount_minor_units": amount_minor_units,
            "originator_conversation_id": idempotency_key,
        }
        async with AsyncServiceClient(
            service_name="commission", base_url=self._base_url
        ) as client:
            response = await client.post(
                "/payments/b2c",
                json=payload,
                headers={
                    "X-Tenant-Id": tenant_id,
                    "Idempotency-Key": idempotency_key,
                    "Content-Type": "application/json",
                },
            )
        if response.status_code not in {200, 201, 202}:
            raise PaymentsClientError(
                f"payments B2C failed: HTTP {response.status_code} {response.text}"
            )
        body = response.json()
        return B2CResult(
            payout_id=UUID(body["payout_id"]),
            state=str(body["state"]),
            amount_minor_units=int(body["amount_minor_units"]),
            conversation_id=body.get("conversation_id"),
        )


class FakePaymentsClient(PaymentsClient):
    """Test double — records calls; no HTTP."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._results: dict[str, B2CResult] = {}
        self.fail_keys: set[str] = set()
        self._next_id = 1

    def clear(self) -> None:
        self.calls.clear()
        self._results.clear()
        self.fail_keys.clear()
        self._next_id = 1

    async def initiate_b2c(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        attendant_id: str,
        phone_number: str,
        amount_minor_units: int,
    ) -> B2CResult:
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "idempotency_key": idempotency_key,
                "attendant_id": attendant_id,
                "phone_number": phone_number,
                "amount_minor_units": amount_minor_units,
            }
        )
        if idempotency_key in self.fail_keys:
            raise PaymentsClientError(f"forced failure for {idempotency_key}")
        if idempotency_key in self._results:
            return self._results[idempotency_key]
        from uuid import uuid4

        result = B2CResult(
            payout_id=uuid4(),
            state="submitted",
            amount_minor_units=amount_minor_units,
            conversation_id=f"fake-b2c-{self._next_id}",
        )
        self._next_id += 1
        self._results[idempotency_key] = result
        return result
