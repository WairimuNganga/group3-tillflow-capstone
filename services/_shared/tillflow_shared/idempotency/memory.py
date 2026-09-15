from __future__ import annotations

import asyncio
from dataclasses import replace

from tillflow_shared.idempotency.store import IdempotencyStore
from tillflow_shared.idempotency.types import IdempotencyRecord, IdempotencyStatus


class InMemoryIdempotencyStore:
    """Test double for idempotency persistence."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str, str], IdempotencyRecord] = {}
        self._lock = asyncio.Lock()

    async def get_record(self, service: str, tenant_id: str, key: str) -> IdempotencyRecord | None:
        async with self._lock:
            return self._records.get((service, tenant_id, key))

    async def try_begin(
        self, service: str, tenant_id: str, key: str, record: IdempotencyRecord
    ) -> bool:
        async with self._lock:
            lookup = (service, tenant_id, key)
            if lookup in self._records:
                return False
            self._records[lookup] = record
            return True

    async def complete(
        self,
        service: str,
        tenant_id: str,
        key: str,
        *,
        status_code: int,
        response_body: dict | list,
    ) -> None:
        async with self._lock:
            lookup = (service, tenant_id, key)
            existing = self._records[lookup]
            self._records[lookup] = replace(
                existing,
                status=IdempotencyStatus.COMPLETED,
                status_code=status_code,
                response_body=response_body,
            )

    def clear(self) -> None:
        self._records.clear()
