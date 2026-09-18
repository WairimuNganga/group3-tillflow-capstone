from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from tillflow_shared.idempotency.types import IdempotencyRecord, IdempotencyStatus

from payments.idempotency.models import IdempotencyKeyRow


class PostgresIdempotencyStore:
    """Postgres-backed idempotency store for the payments schema."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_record(row: IdempotencyKeyRow) -> IdempotencyRecord:
        return IdempotencyRecord(
            service=row.service,
            tenant_id=row.tenant_id,
            key=row.key,
            status=IdempotencyStatus(row.status),
            status_code=row.status_code,
            response_body=row.response_body,
            created_at=row.created_at,
            expires_at=row.expires_at,
        )

    async def get_record(self, service: str, tenant_id: str, key: str) -> IdempotencyRecord | None:
        result = await self._session.execute(
            select(IdempotencyKeyRow).where(
                IdempotencyKeyRow.service == service,
                IdempotencyKeyRow.tenant_id == tenant_id,
                IdempotencyKeyRow.key == key,
            )
        )
        row = result.scalar_one_or_none()
        return self._to_record(row) if row else None

    async def try_begin(
        self, service: str, tenant_id: str, key: str, record: IdempotencyRecord
    ) -> bool:
        stmt = (
            insert(IdempotencyKeyRow)
            .values(
                service=service,
                tenant_id=tenant_id,
                key=key,
                status=record.status.value,
                status_code=record.status_code,
                response_body=record.response_body,
                created_at=record.created_at,
                expires_at=record.expires_at,
            )
            .on_conflict_do_nothing(
                index_elements=["service", "tenant_id", "key"],
            )
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return (result.rowcount or 0) == 1

    async def complete(
        self,
        service: str,
        tenant_id: str,
        key: str,
        *,
        status_code: int,
        response_body: dict | list,
    ) -> None:
        await self._session.execute(
            update(IdempotencyKeyRow)
            .where(
                IdempotencyKeyRow.service == service,
                IdempotencyKeyRow.tenant_id == tenant_id,
                IdempotencyKeyRow.key == key,
            )
            .values(
                status=IdempotencyStatus.COMPLETED.value,
                status_code=status_code,
                response_body=response_body,
            )
        )
        await self._session.commit()
