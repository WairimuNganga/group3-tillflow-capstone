"""Request-scoped telemetry for HTTP services, plus the business-span helper.

``TelemetryMiddleware`` is plain ASGI rather than a Starlette ``BaseHTTPMiddleware``
subclass, which runs the downstream app in a separate task and makes ``contextvars``
propagation unreliable. The tenant id is the one value that must never silently fail
to reach a request handler.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Iterable, Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

from tillflow_shared.otel.context import get_idempotency_key, get_tenant_id, request_context
from tillflow_shared.otel.metrics import RedMetrics, build_red_metrics
from tillflow_shared.otel.pii import redact, redact_text
from tillflow_shared.otel.bootstrap import get_meter, get_tracer

TENANT_HEADER = b"x-tenant-id"
IDEMPOTENCY_HEADER = b"idempotency-key"

# Probes run every few seconds against every task. Counting them would swamp real
# traffic in every panel and inflate the denominator of every SLI in
# slo-error-budgets.md, making the error budget look healthier than it is.
DEFAULT_EXCLUDED_PATHS: tuple[str, ...] = ("/health", "/ready")

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", ()):
        if key == name:
            return value.decode("latin-1")
    return None


def _route_template(scope: Scope) -> str:
    """The parameterised route, never the concrete path.

    A raw path would create one Prometheus series per sale id. ``unmatched`` covers
    404s, which have no route.
    """
    route = scope.get("route")
    template = getattr(route, "path_format", None) or getattr(route, "path", None)
    return template or "unmatched"


def _status_class(status_code: int) -> str:
    """``2xx``/``4xx``/``5xx``, to bound label cardinality."""
    return f"{status_code // 100}xx"


class TelemetryMiddleware:
    """Binds request context, then records the RED metrics for the request."""

    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        *,
        service_name: str,
        excluded_paths: Iterable[str] = DEFAULT_EXCLUDED_PATHS,
        metrics: RedMetrics | None = None,
    ) -> None:
        self.app = app
        self.service_name = service_name
        self.excluded_paths = frozenset(excluded_paths)
        self.metrics = metrics or build_red_metrics(service_name, get_meter())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in self.excluded_paths:
            await self.app(scope, receive, send)
            return

        status_code = 500
        started = time.perf_counter()

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        tenant_id = _header(scope, TENANT_HEADER)
        idempotency_key = _header(scope, IDEMPOTENCY_HEADER)

        with request_context(tenant_id=tenant_id, idempotency_key=idempotency_key):
            span = trace.get_current_span()
            if tenant_id:
                span.set_attribute("tenant_id", tenant_id)
            if idempotency_key:
                span.set_attribute("idempotency_key", idempotency_key)
            try:
                await self.app(scope, receive, send_wrapper)
            except Exception:
                # An unhandled exception never reaches http.response.start, so the
                # request would otherwise go uncounted — and an uncounted failure is
                # invisible to the error budget.
                self._record(scope, 500, started)
                raise
            else:
                self._record(scope, status_code, started)

    def _record(self, scope: Scope, status_code: int, started: float) -> None:
        route = _route_template(scope)
        method = scope.get("method", "UNKNOWN")
        self.metrics.requests_total.add(
            1, {"route": route, "method": method, "status": _status_class(status_code)}
        )
        self.metrics.request_duration_seconds.record(
            time.perf_counter() - started, {"route": route, "method": method}
        )


def instrument_fastapi(
    app: Any,
    *,
    service_name: str,
    excluded_paths: Iterable[str] = DEFAULT_EXCLUDED_PATHS,
) -> None:
    """Attach tracing and RED metrics to a FastAPI app.

    Order matters: Starlette adds each new middleware outside the previous one, so the
    OpenTelemetry server span is installed second to end up outermost. The span then
    already exists when ``TelemetryMiddleware`` runs and can be annotated with the
    tenant id.
    """
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    excluded = tuple(excluded_paths)
    app.add_middleware(TelemetryMiddleware, service_name=service_name, excluded_paths=excluded)
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls=",".join(path.lstrip("/") for path in excluded),
    )


@contextmanager
def traced(name: str, **attributes: Any) -> Iterator[Span]:
    """Open a business span named per ADR-008, e.g. ``traced("payments.stk_push")``.

    The tenant id and idempotency key are attached automatically, which is what makes
    threat model T3.3 — attributing who triggered a payout — hold without every call
    site remembering to do it.
    """
    with get_tracer().start_as_current_span(name) as span:
        tenant_id = get_tenant_id()
        if tenant_id:
            span.set_attribute("tenant_id", tenant_id)
        idempotency_key = get_idempotency_key()
        if idempotency_key:
            span.set_attribute("idempotency_key", idempotency_key)
        for key, value in redact(attributes).items():
            if value is not None:
                span.set_attribute(key, value)

        try:
            yield span
        except Exception as exc:
            # The stack trace is deliberately not recorded onto the span: exception
            # text routinely contains the argument that caused it, and here that can
            # be an MSISDN. The log line carries the full stack.
            span.set_status(Status(StatusCode.ERROR, redact_text(str(exc))))
            span.set_attribute("error.type", type(exc).__name__)
            raise
