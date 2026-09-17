from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID

from payments.domain.models import PaymentCallback, PaymentLedgerEntry


class InMemoryCallbackRepository:
    """Deduped callback store keyed by (merchant_request_id, checkout_request_id)."""

    def __init__(self) -> None:
        self._by_provider: dict[tuple[str, str], PaymentCallback] = {}
        self._next_id = 1
        self._lock = asyncio.Lock()

    async def try_insert(self, callback: PaymentCallback) -> bool:
        """Return True if inserted; False if provider-id pair already exists."""
        async with self._lock:
            key = (callback.merchant_request_id, callback.checkout_request_id)
            if key in self._by_provider:
                return False
            if callback.id is None:
                callback.id = self._next_id
                self._next_id += 1
            self._by_provider[key] = deepcopy(callback)
            return True

    def clear(self) -> None:
        self._by_provider.clear()
        self._next_id = 1


class InMemoryLedgerRepository:
    """Append-only ledger for local/CI."""

    def __init__(self) -> None:
        self._entries: list[PaymentLedgerEntry] = []
        self._next_id = 1
        self._lock = asyncio.Lock()

    async def append(self, entry: PaymentLedgerEntry) -> PaymentLedgerEntry:
        async with self._lock:
            if entry.id is None:
                entry.id = self._next_id
                self._next_id += 1
            stored = deepcopy(entry)
            self._entries.append(stored)
            return deepcopy(stored)

    async def count_for_payment(self, payment_id: UUID, entry_type: str) -> int:
        async with self._lock:
            return sum(
                1
                for e in self._entries
                if e.payment_id == payment_id and e.entry_type == entry_type
            )

    async def count_for_payout(self, payout_id: UUID, entry_type: str) -> int:
        async with self._lock:
            return sum(
                1
                for e in self._entries
                if e.payout_id == payout_id and e.entry_type == entry_type
            )

    async def list_for_payment(self, payment_id: UUID) -> list[PaymentLedgerEntry]:
        async with self._lock:
            return [deepcopy(e) for e in self._entries if e.payment_id == payment_id]

    async def list_for_payout(self, payout_id: UUID) -> list[PaymentLedgerEntry]:
        async with self._lock:
            return [deepcopy(e) for e in self._entries if e.payout_id == payout_id]

    def clear(self) -> None:
        self._entries.clear()
        self._next_id = 1
