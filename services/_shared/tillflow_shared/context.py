"""Request-scoped values shared by the logger, the tracer, and the database layer.

One source of truth per request. The logger reads the tenant id for every line and
the tracer for every span (ADR-008); the database layer reads the same value to set
``app.current_tenant_id`` before any statement runs (ADR-005).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_tenant_id: ContextVar[str | None] = ContextVar("tillflow_tenant_id", default=None)
_idempotency_key: ContextVar[str | None] = ContextVar("tillflow_idempotency_key", default=None)


def get_tenant_id() -> str | None:
    """The tenant this request belongs to, or ``None`` outside a request."""
    return _tenant_id.get()


def get_idempotency_key() -> str | None:
    """The idempotency key of the current money-path operation, if any (ADR-004)."""
    return _idempotency_key.get()


@contextmanager
def request_context(
    *,
    tenant_id: str | None = None,
    idempotency_key: str | None = None,
) -> Iterator[None]:
    """Bind request-scoped values for the duration of the block.

    Resets on exit, including on exception, so one tenant's id cannot leak into the
    next unit of work on a reused thread.
    """
    tenant_token = _tenant_id.set(tenant_id)
    key_token = _idempotency_key.set(idempotency_key)
    try:
        yield
    finally:
        _idempotency_key.reset(key_token)
        _tenant_id.reset(tenant_token)
