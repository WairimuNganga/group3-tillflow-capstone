"""Web → Commission client for period summary, close, and payout."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

import httpx
from tillflow_shared.otel.http_client import AsyncServiceClient


class CommissionUnavailableError(RuntimeError):
    pass


@dataclass
class LedgerLine:
    sale_id: str
    attendant_id: str
    sale_amount_minor_units: int
    rate_bps: int
    commission_minor_units: int


@dataclass
class PayoutIntent:
    attendant_id: str
    state: str
    amount_minor_units: int
    payments_payout_id: str | None = None


@dataclass
class PayoutRow:
    tenant_id: str
    payout_period: str
    attendant_id: str
    phone_number: str
    amount_minor_units: int
    state: str
    payments_payout_id: str | None = None
    failure_reason: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class PeriodSummary:
    payout_period: str
    tenant_id: str
    close_status: str | None
    ledger_lines: list[LedgerLine] = field(default_factory=list)
    ledger_commission_minor_units: int = 0
    payout_intents: list[PayoutIntent] = field(default_factory=list)


class CommissionClient(Protocol):
    async def get_summary(self, *, tenant_id: str, payout_period: date) -> PeriodSummary: ...

    async def list_payouts(
        self,
        *,
        tenant_id: str,
        attendant_id: str | None = None,
        state: str | None = None,
    ) -> list[PayoutRow]: ...

    async def run_close(self, *, payout_period: date) -> dict[str, Any]: ...

    async def run_payout(
        self, *, tenant_id: str, payout_period: date, attendant_id: str
    ) -> dict[str, Any]: ...


class HttpCommissionClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        try:
            async with AsyncServiceClient(
                service_name="web", base_url=self._base_url
            ) as client:
                response = await client.request(
                    method, path, params=params, json=json
                )
                if response.is_error:
                    detail = None
                    try:
                        body = response.json()
                        detail = body.get("detail") if isinstance(body, dict) else None
                    except ValueError:
                        detail = None
                    if isinstance(detail, str) and detail.strip():
                        raise CommissionUnavailableError(detail.strip())
                    response.raise_for_status()
                if not response.content:
                    return {}
                return response.json()
        except CommissionUnavailableError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise CommissionUnavailableError(str(exc)) from exc

    async def get_summary(self, *, tenant_id: str, payout_period: date) -> PeriodSummary:
        body = await self._request(
            "GET",
            "/internal/summary",
            params={
                "tenant_id": tenant_id,
                "payout_period": payout_period.isoformat(),
            },
        )
        return PeriodSummary(
            payout_period=str(body.get("payout_period") or payout_period.isoformat()),
            tenant_id=str(body.get("tenant_id") or tenant_id),
            close_status=body.get("close_status"),
            ledger_lines=[
                LedgerLine(
                    sale_id=str(row["sale_id"]),
                    attendant_id=str(row["attendant_id"]),
                    sale_amount_minor_units=int(
                        row.get("sale_amount_minor_units")
                        or row.get("amount_minor_units")
                        or 0
                    ),
                    rate_bps=int(row["rate_bps"]),
                    commission_minor_units=int(row["commission_minor_units"]),
                )
                for row in (body.get("ledger_lines") or [])
            ],
            ledger_commission_minor_units=int(body.get("ledger_commission_minor_units") or 0),
            payout_intents=[
                PayoutIntent(
                    attendant_id=str(row["attendant_id"]),
                    state=str(row["state"]),
                    amount_minor_units=int(row["amount_minor_units"]),
                    payments_payout_id=(
                        str(row["payments_payout_id"])
                        if row.get("payments_payout_id")
                        else None
                    ),
                )
                for row in (body.get("payout_intents") or [])
            ],
        )

    async def list_payouts(
        self,
        *,
        tenant_id: str,
        attendant_id: str | None = None,
        state: str | None = None,
    ) -> list[PayoutRow]:
        params: dict[str, Any] = {"tenant_id": tenant_id}
        if attendant_id:
            params["attendant_id"] = attendant_id
        if state:
            params["state"] = state
        body = await self._request("GET", "/internal/payouts", params=params)
        return [
            PayoutRow(
                tenant_id=str(row.get("tenant_id") or tenant_id),
                payout_period=str(row["payout_period"]),
                attendant_id=str(row["attendant_id"]),
                phone_number=str(row.get("phone_number") or ""),
                amount_minor_units=int(row["amount_minor_units"]),
                state=str(row["state"]),
                payments_payout_id=(
                    str(row["payments_payout_id"]) if row.get("payments_payout_id") else None
                ),
                failure_reason=(
                    str(row["failure_reason"]) if row.get("failure_reason") else None
                ),
                created_at=str(row.get("created_at") or ""),
                updated_at=str(row.get("updated_at") or ""),
            )
            for row in (body.get("payouts") or [])
        ]

    async def run_close(self, *, payout_period: date) -> dict[str, Any]:
        body = await self._request(
            "POST",
            "/internal/close",
            json={"payout_period": payout_period.isoformat()},
        )
        return body if isinstance(body, dict) else {}

    async def run_payout(
        self, *, tenant_id: str, payout_period: date, attendant_id: str
    ) -> dict[str, Any]:
        body = await self._request(
            "POST",
            "/internal/payout",
            json={
                "tenant_id": tenant_id,
                "payout_period": payout_period.isoformat(),
                "attendant_id": attendant_id,
            },
        )
        return body if isinstance(body, dict) else {}


@dataclass
class FakeCommissionClient:
    """In-process commission for web tests without a running commission service."""

    summaries: dict[tuple[str, str], PeriodSummary] = field(default_factory=dict)
    payout_rows: list[PayoutRow] = field(default_factory=list)
    closes: list[str] = field(default_factory=list)
    payouts: list[tuple[str, str, str]] = field(default_factory=list)

    async def get_summary(self, *, tenant_id: str, payout_period: date) -> PeriodSummary:
        key = (tenant_id, payout_period.isoformat())
        return self.summaries.get(
            key,
            PeriodSummary(
                payout_period=payout_period.isoformat(),
                tenant_id=tenant_id,
                close_status=None,
            ),
        )

    async def list_payouts(
        self,
        *,
        tenant_id: str,
        attendant_id: str | None = None,
        state: str | None = None,
    ) -> list[PayoutRow]:
        rows = [r for r in self.payout_rows if r.tenant_id == tenant_id]
        if attendant_id:
            rows = [r for r in rows if r.attendant_id == attendant_id]
        if state:
            rows = [r for r in rows if r.state == state]
        return rows

    async def run_close(self, *, payout_period: date) -> dict[str, Any]:
        self.closes.append(payout_period.isoformat())
        return {
            "payout_period": payout_period.isoformat(),
            "status": "completed",
            "ledger_lines_written": 0,
            "intents_enqueued": 0,
            "skipped_mismatch": 0,
            "already_completed": False,
        }

    async def run_payout(
        self, *, tenant_id: str, payout_period: date, attendant_id: str
    ) -> dict[str, Any]:
        self.payouts.append((tenant_id, payout_period.isoformat(), attendant_id))
        return {
            "tenant_id": tenant_id,
            "payout_period": payout_period.isoformat(),
            "attendant_id": attendant_id,
            "state": "submitted",
            "amount_minor_units": 0,
            "payments_payout_id": "fake-payout",
            "already_requested": False,
            "next_payout_period": (payout_period + timedelta(days=1)).isoformat(),
        }
