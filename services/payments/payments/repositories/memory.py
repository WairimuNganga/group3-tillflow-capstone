from __future__ import annotations

import asyncio
from copy import deepcopy
from uuid import UUID

from payments.domain.models import Payment
from payments.domain.state import PaymentState


class InMemoryPaymentRepository:
    """Test / local double for payment persistence until RDS is wired."""

    def __init__(self) -> None:
        self._by_id: dict[UUID, Payment] = {}
        self._lock = asyncio.Lock()

    async def get_by_tenant_and_sale(self, tenant_id: str, sale_id: UUID) -> Payment | None:
        async with self._lock:
            for payment in self._by_id.values():
                if payment.tenant_id == tenant_id and payment.sale_id == sale_id:
                    return deepcopy(payment)
            return None

    async def get_by_tenant_and_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> Payment | None:
        async with self._lock:
            for payment in self._by_id.values():
                if payment.tenant_id == tenant_id and payment.idempotency_key == idempotency_key:
                    return deepcopy(payment)
            return None

    async def get_by_checkout_request_id(self, checkout_request_id: str) -> Payment | None:
        async with self._lock:
            for payment in self._by_id.values():
                if payment.checkout_request_id == checkout_request_id:
                    return deepcopy(payment)
            return None

    async def get_by_id(self, payment_id: UUID) -> Payment | None:
        async with self._lock:
            payment = self._by_id.get(payment_id)
            return deepcopy(payment) if payment else None

    async def save(self, payment: Payment) -> Payment:
        async with self._lock:
            for existing in self._by_id.values():
                if existing.tenant_id == payment.tenant_id and existing.sale_id == payment.sale_id:
                    raise ValueError("payment already exists for tenant/sale")
                if (
                    existing.tenant_id == payment.tenant_id
                    and existing.idempotency_key == payment.idempotency_key
                ):
                    raise ValueError("payment already exists for tenant/idempotency key")
            self._by_id[payment.id] = deepcopy(payment)
            return deepcopy(payment)

    async def update(self, payment: Payment) -> Payment:
        async with self._lock:
            if payment.id not in self._by_id:
                raise KeyError(f"payment not found: {payment.id}")
            self._by_id[payment.id] = deepcopy(payment)
            return deepcopy(payment)

    def clear(self) -> None:
        self._by_id.clear()
