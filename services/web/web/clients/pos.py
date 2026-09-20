from __future__ import annotations

import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from tillflow_shared.otel.http_client import AsyncServiceClient


class PosUnavailableError(RuntimeError):
    pass


@dataclass
class DemoShop:
    tenant_id: str
    till_id: str
    attendant_id: str
    shop_name: str
    attendant_name: str
    attendant_phone: str


@dataclass
class DemoSale:
    sale_id: str
    status: str
    total_minor: int
    payment_id: str | None = None
    payment_state: str | None = None
    attendant_id: str | None = None
    attendant_name: str | None = None
    customer_msisdn: str | None = None
    created_at: str | None = None
    item_name: str | None = None
    tenant_id: str | None = None


SALE_STATUSES = (
    "pending",
    "awaiting_payment",
    "paid",
    "failed",
    "cancelled",
)


def commission_minor(amount_minor_units: int, rate_bps: int) -> int:
    """Same floor math as the commission worker: amount * rate_bps / 10000."""
    if amount_minor_units < 0 or rate_bps < 0:
        raise ValueError("amount and rate_bps must be non-negative")
    return (amount_minor_units * rate_bps) // 10000


def format_kes_from_minor(minor_units: int) -> str:
    whole, cents = divmod(int(minor_units), 100)
    return f"{whole}.{cents:02d}"


class PosClient(Protocol):
    async def ensure_shop(
        self,
        *,
        shop_name: str,
        owner_phone: str,
        attendant_name: str,
        attendant_phone: str,
        shortcode: str,
        rate_bps: int = 200,
    ) -> DemoShop: ...

    async def create_and_pay(
        self,
        *,
        tenant_id: str,
        till_id: str,
        attendant_id: str,
        item_name: str,
        amount_minor: int,
        customer_phone: str,
    ) -> DemoSale: ...

    async def get_sale(self, *, tenant_id: str, sale_id: str) -> DemoSale: ...

    async def list_sales(self, *, tenant_id: str) -> list[DemoSale]: ...

    async def list_commission_rates(self, *, tenant_id: str) -> dict[str, int]: ...


class HttpPosClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        tenant_id: str | None = None,
        idempotency_key: str | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        headers: dict[str, str] = {}
        if tenant_id:
            headers["X-Tenant-Id"] = tenant_id
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            async with AsyncServiceClient(
                service_name="web", base_url=self._base_url
            ) as client:
                response = await client.request(method, path, json=json, headers=headers)
                response.raise_for_status()
                if not response.content:
                    return {}
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PosUnavailableError(str(exc)) from exc

    @staticmethod
    def _sale_from_body(body: dict[str, Any], *, attendant_name: str | None = None) -> DemoSale:
        items = body.get("items") or []
        item_name = None
        if items and isinstance(items[0], dict):
            item_name = str(items[0].get("name") or "") or None
        created = body.get("created_at")
        return DemoSale(
            sale_id=str(body["id"]),
            status=str(body["status"]),
            total_minor=int(body["total_minor"]),
            payment_id=str(body["payment_id"]) if body.get("payment_id") else None,
            payment_state=None,
            attendant_id=str(body["attendant_id"]) if body.get("attendant_id") else None,
            attendant_name=attendant_name,
            customer_msisdn=body.get("customer_msisdn"),
            created_at=str(created) if created else None,
            item_name=item_name,
            tenant_id=str(body["tenant_id"]) if body.get("tenant_id") else None,
        )

    async def ensure_shop(
        self,
        *,
        shop_name: str,
        owner_phone: str,
        attendant_name: str,
        attendant_phone: str,
        shortcode: str,
        rate_bps: int = 200,
    ) -> DemoShop:
        tenant_body = await self._request(
            "POST",
            "/tenants",
            json={
                "name": shop_name,
                "owner_phone": owner_phone,
                "owner_name": "Owner",
            },
        )
        tenant_id = str(tenant_body["tenant"]["id"])
        till = await self._request(
            "POST",
            "/tills",
            tenant_id=tenant_id,
            json={"name": "Front counter", "shortcode": shortcode},
        )
        attendant = await self._request(
            "POST",
            "/attendants",
            tenant_id=tenant_id,
            json={"phone": attendant_phone, "display_name": attendant_name},
        )
        attendant_id = str(attendant["id"])
        with suppress(PosUnavailableError):
            await self._request(
                "POST",
                "/commission-rates",
                tenant_id=tenant_id,
                json={"attendant_id": attendant_id, "rate_bps": rate_bps},
            )
        return DemoShop(
            tenant_id=tenant_id,
            till_id=str(till["id"]),
            attendant_id=attendant_id,
            shop_name=shop_name,
            attendant_name=attendant_name,
            attendant_phone=attendant_phone,
        )

    async def create_and_pay(
        self,
        *,
        tenant_id: str,
        till_id: str,
        attendant_id: str,
        item_name: str,
        amount_minor: int,
        customer_phone: str,
    ) -> DemoSale:
        sale = await self._request(
            "POST",
            "/sales",
            tenant_id=tenant_id,
            idempotency_key=f"web-{uuid.uuid4()}",
            json={
                "till_id": till_id,
                "attendant_id": attendant_id,
                "customer_msisdn": customer_phone,
                "items": [
                    {
                        "name": item_name,
                        "quantity": 1,
                        "unit_price_minor": amount_minor,
                    }
                ],
            },
        )
        sale_id = str(sale["id"])
        pay = await self._request(
            "POST",
            f"/sales/{sale_id}/pay",
            tenant_id=tenant_id,
            json={"phone_number": customer_phone},
        )
        mapped = self._sale_from_body(sale)
        mapped.status = str(pay.get("status") or mapped.status or "awaiting_payment")
        mapped.payment_id = str(pay["payment_id"]) if pay.get("payment_id") else None
        mapped.payment_state = pay.get("payment_state")
        mapped.attendant_id = attendant_id
        mapped.item_name = item_name
        mapped.customer_msisdn = customer_phone
        mapped.tenant_id = tenant_id
        return mapped

    async def get_sale(self, *, tenant_id: str, sale_id: str) -> DemoSale:
        body = await self._request("GET", f"/sales/{sale_id}", tenant_id=tenant_id)
        return self._sale_from_body(body)

    async def list_sales(self, *, tenant_id: str) -> list[DemoSale]:
        body = await self._request("GET", "/sales", tenant_id=tenant_id)
        if not isinstance(body, list):
            raise PosUnavailableError("unexpected sales list response")
        return [self._sale_from_body(row) for row in body if isinstance(row, dict)]

    async def list_commission_rates(self, *, tenant_id: str) -> dict[str, int]:
        """Latest rate_bps per attendant_id (highest effective_from wins)."""
        body = await self._request("GET", "/commission-rates", tenant_id=tenant_id)
        if not isinstance(body, list):
            raise PosUnavailableError("unexpected commission-rates response")
        rates: dict[str, tuple[str, int]] = {}
        for row in body:
            if not isinstance(row, dict):
                continue
            attendant_id = str(row.get("attendant_id") or "")
            if not attendant_id:
                continue
            effective = str(row.get("effective_from") or "")
            rate_bps = int(row["rate_bps"])
            prev = rates.get(attendant_id)
            if prev is None or effective >= prev[0]:
                rates[attendant_id] = (effective, rate_bps)
        return {aid: bps for aid, (_eff, bps) in rates.items()}


@dataclass
class FakePosClient:
    """In-process POS for local web tests without a running POS service."""

    shops: dict[str, DemoShop] = field(default_factory=dict)
    sales: dict[str, DemoSale] = field(default_factory=dict)
    rates: dict[str, dict[str, int]] = field(default_factory=dict)

    async def ensure_shop(
        self,
        *,
        shop_name: str,
        owner_phone: str,
        attendant_name: str,
        attendant_phone: str,
        shortcode: str,
        rate_bps: int = 200,
    ) -> DemoShop:
        del owner_phone, shortcode
        shop = DemoShop(
            tenant_id=str(uuid.uuid4()),
            till_id=str(uuid.uuid4()),
            attendant_id=str(uuid.uuid4()),
            shop_name=shop_name,
            attendant_name=attendant_name,
            attendant_phone=attendant_phone,
        )
        self.shops[shop.tenant_id] = shop
        self.rates[shop.tenant_id] = {shop.attendant_id: rate_bps}
        return shop

    async def create_and_pay(
        self,
        *,
        tenant_id: str,
        till_id: str,
        attendant_id: str,
        item_name: str,
        amount_minor: int,
        customer_phone: str,
    ) -> DemoSale:
        del till_id
        shop = self.shops.get(tenant_id)
        sale = DemoSale(
            sale_id=str(uuid.uuid4()),
            status="awaiting_payment",
            total_minor=amount_minor,
            payment_id=str(uuid.uuid4()),
            payment_state="stk_sent",
            attendant_id=attendant_id,
            attendant_name=shop.attendant_name if shop else None,
            customer_msisdn=customer_phone,
            created_at="2026-09-20T12:00:00Z",
            item_name=item_name,
            tenant_id=tenant_id,
        )
        self.sales[sale.sale_id] = sale
        self.shops.setdefault(
            tenant_id,
            DemoShop(
                tenant_id=tenant_id,
                till_id=str(uuid.uuid4()),
                attendant_id=attendant_id,
                shop_name="Demo",
                attendant_name="Attendant",
                attendant_phone="254700000000",
            ),
        )
        self.rates.setdefault(tenant_id, {}).setdefault(attendant_id, 200)
        return sale

    async def get_sale(self, *, tenant_id: str, sale_id: str) -> DemoSale:
        del tenant_id
        sale = self.sales.get(sale_id)
        if sale is None:
            raise PosUnavailableError("sale not found")
        return sale

    async def list_sales(self, *, tenant_id: str) -> list[DemoSale]:
        shop = self.shops.get(tenant_id)
        sales = [s for s in self.sales.values() if s.tenant_id == tenant_id]
        for sale in sales:
            if shop and sale.attendant_id == shop.attendant_id:
                sale.attendant_name = shop.attendant_name
        return sorted(sales, key=lambda s: s.created_at or "", reverse=True)

    async def list_commission_rates(self, *, tenant_id: str) -> dict[str, int]:
        return dict(self.rates.get(tenant_id) or {})
