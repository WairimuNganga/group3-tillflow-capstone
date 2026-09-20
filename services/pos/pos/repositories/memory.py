"""In-memory POS repository — local/CI double when DATABASE_URL is unset.

It emulates the tenant-scoped uniqueness and composite foreign keys the Postgres
schema enforces, so service logic behaves the same either way. It does NOT
emulate RLS — DB-enforced tenant isolation is proved against real Postgres
(ADR-005). Reads filter by ``tenant_id`` explicitly, mirroring the app-layer
scoping the Postgres repo also does.
"""

from __future__ import annotations

import asyncio
import uuid
from copy import deepcopy
from datetime import UTC, datetime

from pos.domain.models import CommissionRate, Sale, Tenant, Till, User
from pos.repositories.errors import AlreadyExistsError, InvalidReferenceError


def _fill_timestamps(obj: object) -> None:
    """Emulate the Postgres server defaults the memory double doesn't get."""
    now = datetime.now(UTC)
    for attr in ("created_at", "updated_at", "effective_from"):
        if hasattr(obj, attr) and getattr(obj, attr) is None:
            setattr(obj, attr, now)


class InMemoryPosRepository:
    def __init__(self) -> None:
        self._tenants: dict[uuid.UUID, Tenant] = {}
        self._users: dict[uuid.UUID, User] = {}
        self._tills: dict[uuid.UUID, Till] = {}
        self._sales: dict[uuid.UUID, Sale] = {}
        self._rates: dict[uuid.UUID, CommissionRate] = {}
        self._lock = asyncio.Lock()

    async def set_tenant(self, tenant_id: uuid.UUID) -> None:  # noqa: D401 - no GUC in memory
        return None

    async def create_tenant(self, tenant: Tenant) -> Tenant:
        async with self._lock:
            tenant.id = tenant.id or uuid.uuid4()
            tenant.status = tenant.status or "active"
            _fill_timestamps(tenant)
            self._tenants[tenant.id] = deepcopy(tenant)
            return deepcopy(tenant)

    async def create_user(self, user: User) -> User:
        async with self._lock:
            for existing in self._users.values():
                if existing.tenant_id == user.tenant_id and existing.phone == user.phone:
                    raise AlreadyExistsError("phone already exists for tenant")
            user.id = user.id or uuid.uuid4()
            user.status = user.status or "active"
            _fill_timestamps(user)
            self._users[user.id] = deepcopy(user)
            return deepcopy(user)

    async def create_till(self, till: Till) -> Till:
        async with self._lock:
            for existing in self._tills.values():
                if existing.tenant_id == till.tenant_id and existing.shortcode == till.shortcode:
                    raise AlreadyExistsError("shortcode already exists for tenant")
            till.id = till.id or uuid.uuid4()
            till.status = till.status or "active"
            _fill_timestamps(till)
            self._tills[till.id] = deepcopy(till)
            return deepcopy(till)

    async def get_sale_by_idempotency(
        self, tenant_id: uuid.UUID, idempotency_key: str
    ) -> Sale | None:
        async with self._lock:
            for sale in self._sales.values():
                if sale.tenant_id == tenant_id and sale.idempotency_key == idempotency_key:
                    return deepcopy(sale)
            return None

    async def create_sale(self, sale: Sale) -> Sale:
        async with self._lock:
            # composite FK: till + attendant must exist for this tenant
            till_ok = any(
                t.id == sale.till_id and t.tenant_id == sale.tenant_id
                for t in self._tills.values()
            )
            att_ok = any(
                u.id == sale.attendant_id and u.tenant_id == sale.tenant_id
                for u in self._users.values()
            )
            if not (till_ok and att_ok):
                raise InvalidReferenceError("till_id or attendant_id not found for tenant")
            for existing in self._sales.values():
                if (
                    existing.tenant_id == sale.tenant_id
                    and existing.idempotency_key == sale.idempotency_key
                ):
                    raise AlreadyExistsError("idempotency key already used for tenant")
            sale.id = sale.id or uuid.uuid4()
            sale.currency = sale.currency or "KES"
            _fill_timestamps(sale)
            for item in sale.items:
                item.id = item.id or uuid.uuid4()
                item.sale_id = sale.id
                _fill_timestamps(item)
            self._sales[sale.id] = deepcopy(sale)
            return deepcopy(sale)

    async def get_sale(self, tenant_id: uuid.UUID, sale_id: uuid.UUID) -> Sale | None:
        async with self._lock:
            sale = self._sales.get(sale_id)
            if sale is None or sale.tenant_id != tenant_id:
                return None
            return deepcopy(sale)

    async def list_sales(self, tenant_id: uuid.UUID) -> list[Sale]:
        async with self._lock:
            sales = [deepcopy(s) for s in self._sales.values() if s.tenant_id == tenant_id]
            return sorted(sales, key=lambda s: s.created_at or 0, reverse=True)

    async def update_sale(self, sale: Sale) -> Sale:
        async with self._lock:
            if sale.id not in self._sales:
                raise KeyError(f"sale not found: {sale.id}")
            self._sales[sale.id] = deepcopy(sale)
            return deepcopy(sale)

    async def create_commission_rate(self, rate: CommissionRate) -> CommissionRate:
        async with self._lock:
            attendant = self._users.get(rate.attendant_id)
            if attendant is None or attendant.tenant_id != rate.tenant_id:
                raise InvalidReferenceError("attendant not found for tenant")
            if attendant.role != "attendant":
                raise InvalidReferenceError("commission rate requires an attendant")
            for existing in self._rates.values():
                if (
                    existing.tenant_id == rate.tenant_id
                    and existing.attendant_id == rate.attendant_id
                    and existing.effective_from == rate.effective_from
                ):
                    raise AlreadyExistsError("rate already exists for attendant/effective_from")
            rate.id = rate.id or uuid.uuid4()
            _fill_timestamps(rate)
            self._rates[rate.id] = deepcopy(rate)
            return deepcopy(rate)

    async def list_commission_rates(
        self, tenant_id: uuid.UUID, attendant_id: uuid.UUID | None = None
    ) -> list[CommissionRate]:
        async with self._lock:
            rows = [
                deepcopy(r)
                for r in self._rates.values()
                if r.tenant_id == tenant_id
                and (attendant_id is None or r.attendant_id == attendant_id)
            ]
            return sorted(rows, key=lambda r: r.effective_from or datetime.min.replace(tzinfo=UTC))

    def clear(self) -> None:
        self._tenants.clear()
        self._users.clear()
        self._tills.clear()
        self._sales.clear()
        self._rates.clear()
