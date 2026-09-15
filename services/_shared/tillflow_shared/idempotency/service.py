from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tillflow_shared.idempotency.exceptions import (
    IdempotencyConflictError,
    IdempotencyReplay,
    IdempotencyTenantMismatchError,
)
from tillflow_shared.idempotency.store import IdempotencyStore
from tillflow_shared.idempotency.types import IdempotencyRecord, IdempotencyStatus


class IdempotencyService:
    """Begin / complete guard used by money-path handlers ([ADR-004])."""

    def __init__(
        self,
        store: IdempotencyStore,
        *,
        service_name: str,
        retention_days: int = 14,
    ) -> None:
        self._store = store
        self._service_name = service_name
        self._retention = timedelta(days=retention_days)

    async def begin(self, tenant_id: str, key: str) -> None:
        """Reserve a key or raise ``IdempotencyReplay`` with the stored response."""
        existing = await self._store.get_record(self._service_name, tenant_id, key)
        if existing is not None:
            if existing.tenant_id != tenant_id:
                raise IdempotencyTenantMismatchError(
                    "idempotency key belongs to a different tenant"
                )
            if existing.is_replay:
                raise IdempotencyReplay(existing)
            raise IdempotencyConflictError("idempotency key already in progress")

        now = datetime.now(UTC)
        pending = IdempotencyRecord(
            service=self._service_name,
            tenant_id=tenant_id,
            key=key,
            status=IdempotencyStatus.IN_PROGRESS,
            status_code=None,
            response_body=None,
            created_at=now,
            expires_at=now + self._retention,
        )
        if not await self._store.try_begin(self._service_name, tenant_id, key, pending):
            existing = await self._store.get_record(self._service_name, tenant_id, key)
            if existing is None:
                raise IdempotencyConflictError("idempotency key already in progress")
            if existing.is_replay:
                raise IdempotencyReplay(existing)
            raise IdempotencyConflictError("idempotency key already in progress")

    async def complete(
        self,
        tenant_id: str,
        key: str,
        *,
        status_code: int,
        response_body: dict | list,
    ) -> None:
        await self._store.complete(
            self._service_name,
            tenant_id,
            key,
            status_code=status_code,
            response_body=response_body,
        )
