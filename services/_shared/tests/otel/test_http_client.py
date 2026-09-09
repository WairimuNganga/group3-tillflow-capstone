"""Outbound propagation: the trace and the tenant reach the next service."""

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.propagate import extract

from tillflow_shared.otel.context import request_context
from tillflow_shared.otel.http_client import AsyncServiceClient, ServiceClient


@pytest.fixture
def outbound():
    """Records the headers of whatever the client sends, without a network call."""
    seen: dict[str, httpx.Headers] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        return httpx.Response(200, json={"ok": True})

    return seen, httpx.MockTransport(handler)


def call(transport, **client_kwargs) -> None:
    with ServiceClient(
        service_name="pos",
        base_url="http://payments",
        transport=transport,
        **client_kwargs,
    ) as client:
        client.get("/payments")


def test_traceparent_is_injected(outbound):
    seen, transport = outbound
    call(transport)

    assert "traceparent" in seen["headers"]


def test_downstream_joins_the_same_trace(outbound):
    """The whole point: one sale and its payment are one trace, not two."""
    seen, transport = outbound
    tracer = trace.get_tracer("tests")

    with tracer.start_as_current_span("pos.create_sale") as parent:
        call(transport)
        expected_trace_id = parent.get_span_context().trace_id

    received = trace.get_current_span(extract(dict(seen["headers"]))).get_span_context()
    assert received.trace_id == expected_trace_id
    assert received.is_valid


def test_tenant_and_idempotency_key_are_forwarded(outbound):
    seen, transport = outbound

    with request_context(tenant_id="dukawala-42", idempotency_key="key-abc"):
        call(transport)

    assert seen["headers"]["x-tenant-id"] == "dukawala-42"
    assert seen["headers"]["idempotency-key"] == "key-abc"


def test_explicit_headers_win(outbound):
    seen, transport = outbound

    with request_context(tenant_id="dukawala-42"):
        with ServiceClient(
            service_name="commission", base_url="http://payments", transport=transport
        ) as client:
            client.get("/payments", headers={"X-Tenant-Id": "explicit-tenant"})

    assert seen["headers"]["x-tenant-id"] == "explicit-tenant"


def test_no_tenant_header_outside_a_request(outbound):
    seen, transport = outbound
    call(transport)

    assert "x-tenant-id" not in seen["headers"]


def test_timeout_is_bounded_by_default(outbound):
    """An unbounded call turns another service's slowdown into this service's outage."""
    _, transport = outbound

    with ServiceClient(
        service_name="pos", base_url="http://payments", transport=transport
    ) as client:
        assert client.timeout.read == 5.0
        assert client.timeout.connect == 2.0


async def test_async_client_propagates_too(outbound):
    seen, transport = outbound

    async with AsyncServiceClient(
        service_name="pos", base_url="http://payments", transport=transport
    ) as client:
        with request_context(tenant_id="dukawala-42"):
            await client.get("/payments")

    assert "traceparent" in seen["headers"]
    assert seen["headers"]["x-tenant-id"] == "dukawala-42"
