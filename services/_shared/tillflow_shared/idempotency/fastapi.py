from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette import status

from tillflow_shared.idempotency.exceptions import (
    IdempotencyConflictError,
    IdempotencyReplay,
    IdempotencyRequiredError,
    IdempotencyTenantMismatchError,
)
from tillflow_shared.idempotency.service import IdempotencyService
from tillflow_shared.idempotency.store import IdempotencyStore


class IdempotencyHandle:
    """Request-scoped idempotency reservation for a money-path handler."""

    def __init__(self, service: IdempotencyService, tenant_id: str, key: str) -> None:
        self._service = service
        self.tenant_id = tenant_id
        self.key = key
        self._completed = False

    async def begin(self) -> None:
        await self._service.begin(self.tenant_id, self.key)

    async def complete(self, *, status_code: int, response_body: dict | list) -> None:
        await self._service.complete(
            self.tenant_id,
            self.key,
            status_code=status_code,
            response_body=response_body,
        )
        self._completed = True


def idempotency_handle(
    store: IdempotencyStore,
    *,
    service_name: str,
    retention_days: int = 14,
) -> Callable[..., IdempotencyHandle]:
    """FastAPI dependency factory for money-path routes."""

    service = IdempotencyService(
        store,
        service_name=service_name,
        retention_days=retention_days,
    )

    def _dependency(
        tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> IdempotencyHandle:
        if not tenant_id or not idempotency_key:
            raise IdempotencyRequiredError("X-Tenant-Id and Idempotency-Key are required")
        return IdempotencyHandle(service, tenant_id, idempotency_key)

    return _dependency


def register_idempotency_handlers(app: Any) -> None:
    """Register exception handlers that turn idempotency outcomes into HTTP responses."""

    @app.exception_handler(IdempotencyReplay)
    async def _replay(_request: Request, exc: IdempotencyReplay) -> Response:
        record = exc.record
        return JSONResponse(
            status_code=record.status_code or status.HTTP_200_OK,
            content=record.response_body,
        )

    @app.exception_handler(IdempotencyRequiredError)
    async def _required(_request: Request, _exc: IdempotencyRequiredError) -> Response:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "X-Tenant-Id and Idempotency-Key are required"},
        )

    @app.exception_handler(IdempotencyTenantMismatchError)
    async def _tenant_mismatch(_request: Request, _exc: IdempotencyTenantMismatchError) -> Response:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": "idempotency key tenant mismatch"},
        )

    @app.exception_handler(IdempotencyConflictError)
    async def _conflict(_request: Request, _exc: IdempotencyConflictError) -> Response:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "idempotency key already in progress; retry shortly"},
        )
