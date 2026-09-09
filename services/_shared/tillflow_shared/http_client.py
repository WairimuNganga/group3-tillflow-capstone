"""Outbound HTTP that carries the trace and the request context to the next service.

Without this, a sale created in ``pos`` and the payment it triggers in ``payments``
are two unrelated traces, and the downstream service logs ``tenant_id: null`` on every
line — which breaks the attribution control in threat model T3.3.

Use these instead of a bare ``httpx`` client for any service-to-service call:

    with ServiceClient(service_name="commission", base_url=PAYMENTS_URL) as client:
        client.post("/b2c", json=payload)

The idempotency key is forwarded deliberately: the plan requires Commission to call
the Payments B2C endpoint with the *same* key it used for its own ledger line, so the
two dedupe layers agree on identity. An explicit header on the call always wins.
"""

from __future__ import annotations

from typing import Any

import httpx
from opentelemetry.propagate import inject

from tillflow_shared.context import get_idempotency_key, get_tenant_id
from tillflow_shared.middleware import traced

TENANT_HEADER = "X-Tenant-Id"
IDEMPOTENCY_HEADER = "Idempotency-Key"

# Bounded by default. An unbounded call to another service turns that service's
# slowdown into this service's outage.
DEFAULT_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


def _propagate(headers: httpx.Headers) -> None:
    """Add trace context, tenant and idempotency key to an outbound request."""
    inject(headers)

    tenant_id = get_tenant_id()
    if tenant_id and TENANT_HEADER not in headers:
        headers[TENANT_HEADER] = tenant_id

    idempotency_key = get_idempotency_key()
    if idempotency_key and IDEMPOTENCY_HEADER not in headers:
        headers[IDEMPOTENCY_HEADER] = idempotency_key


def _client_span(service_name: str, request: httpx.Request):
    return traced(
        f"{service_name}.http_request",
        **{"http.request.method": request.method, "url.full": str(request.url)},
    )


class ServiceClient(httpx.Client):
    """A synchronous client for calling another TillFlow service."""

    def __init__(
        self,
        *,
        service_name: str,
        timeout: Any = DEFAULT_TIMEOUT,
        **kwargs: Any,
    ) -> None:
        super().__init__(timeout=timeout, **kwargs)
        self.service_name = service_name

    def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        with _client_span(self.service_name, request) as span:
            _propagate(request.headers)
            response = super().send(request, **kwargs)
            span.set_attribute("http.response.status_code", response.status_code)
            return response


class AsyncServiceClient(httpx.AsyncClient):
    """The same, for async request handlers."""

    def __init__(
        self,
        *,
        service_name: str,
        timeout: Any = DEFAULT_TIMEOUT,
        **kwargs: Any,
    ) -> None:
        super().__init__(timeout=timeout, **kwargs)
        self.service_name = service_name

    async def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        with _client_span(self.service_name, request) as span:
            _propagate(request.headers)
            response = await super().send(request, **kwargs)
            span.set_attribute("http.response.status_code", response.status_code)
            return response
