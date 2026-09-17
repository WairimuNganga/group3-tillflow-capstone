from typing import Protocol

from tillflow_shared.idempotency.types import IdempotencyRecord


class IdempotencyStore(Protocol):
    """Persistence for idempotency records — one implementation per service schema."""

    async def get_record(self, service: str, tenant_id: str, key: str) -> IdempotencyRecord | None: ...

    async def try_begin(
        self, service: str, tenant_id: str, key: str, record: IdempotencyRecord
    ) -> bool:
        """Insert an in-progress record. Return False if the key already exists."""
        ...

    async def complete(
        self,
        service: str,
        tenant_id: str,
        key: str,
        *,
        status_code: int,
        response_body: dict | list,
    ) -> None: ...
