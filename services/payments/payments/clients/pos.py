"""Payments -> POS: report the outcome of a collection.

POS owns sale state, but only Payments knows whether M-Pesa actually took the
money. Once a payment settles — via callback or reconciliation — Payments tells
POS, which moves the sale to ``paid`` / ``failed`` ([ADR-004]).

The call is deliberately best-effort: POS being briefly unreachable must not
undo a settled payment or fail the callback Daraja is waiting on. The payment
stays the source of truth and reconciliation re-reports the same result, which
POS applies idempotently.
"""

from __future__ import annotations

import logging
from typing import Protocol

from tillflow_shared.money import from_whole_kes
from tillflow_shared.otel import business_counter
from tillflow_shared.otel.http_client import AsyncServiceClient

from payments.domain.models import Payment
from payments.domain.state import PaymentState

_log = logging.getLogger(__name__)

pos_notified = business_counter(
    "payments_pos_notifications_total",
    "Sale payment-result notifications sent to POS, by outcome.",
)


def result_idempotency_key(payment: Payment) -> str:
    """One result per payment, however many times it is re-reported."""
    return f"payment-result-{payment.id}"


def _path(payment: Payment) -> str:
    return f"/internal/sales/{payment.sale_id}/payment-result"


def _payload(payment: Payment) -> dict:
    paid = payment.payment_state is PaymentState.PAID
    return {
        "payment_id": str(payment.id),
        "result": "paid" if paid else "failed",
        "amount_minor_units": from_whole_kes(payment.amount_whole_kes),
        "mpesa_receipt": payment.mpesa_receipt_number if paid else None,
        "failure_reason": None if paid else payment.failure_reason,
        "occurred_at": (payment.settled_at or payment.updated_at).isoformat(),
    }


class PosClient(Protocol):
    async def report_payment_result(self, payment: Payment) -> bool: ...


class HttpPosClient:
    """Calls POS over HTTP (Service Connect in AWS), carrying trace + tenant."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def report_payment_result(self, payment: Payment) -> bool:
        headers = {
            "X-Tenant-Id": payment.tenant_id,
            "Idempotency-Key": result_idempotency_key(payment),
        }
        async with AsyncServiceClient(service_name="payments", base_url=self._base_url) as client:
            response = await client.post(_path(payment), json=_payload(payment), headers=headers)
            response.raise_for_status()
        return True


async def notify_pos(client: PosClient | None, payment: Payment) -> bool:
    """Report a settled payment to POS. Never raises — see module docstring."""
    if client is None:
        pos_notified.add(1, {"result": "not_configured"})
        return False
    try:
        await client.report_payment_result(payment)
    except Exception as exc:  # noqa: BLE001 - best effort by design (see docstring)
        pos_notified.add(1, {"result": "error"})
        _log.warning(
            "could not report payment result to POS",
            extra={
                "payment_id": str(payment.id),
                "sale_id": str(payment.sale_id),
                "error": str(exc),
            },
        )
        return False
    pos_notified.add(1, {"result": "ok"})
    return True
