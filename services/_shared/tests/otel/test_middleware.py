"""Context propagation, RED metrics, and the exclusions that keep SLIs honest."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from tillflow_shared.otel.context import get_idempotency_key, get_tenant_id
from tillflow_shared.otel.metrics import build_red_metrics
from tillflow_shared.otel.middleware import TelemetryMiddleware, traced


@pytest.fixture
def client_and_reader():
    """A POS-shaped app with its own in-memory metric reader."""
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    metrics = build_red_metrics("pos", provider.get_meter("tests"))

    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/sales/{sale_id}")
    def get_sale(sale_id: str):
        return {
            "sale_id": sale_id,
            "tenant_id": get_tenant_id(),
            "idempotency_key": get_idempotency_key(),
        }

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    app.add_middleware(TelemetryMiddleware, service_name="pos", metrics=metrics)
    return TestClient(app, raise_server_exceptions=False), reader


def data_points(reader, metric_name):
    points = []
    data = reader.get_metrics_data()
    if data is None:
        # The reader returns None, not an empty envelope, when nothing was recorded.
        return points
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name == metric_name:
                    points.extend(metric.data.data_points)
    return points


def test_request_headers_reach_the_handler(client_and_reader):
    """Why this middleware is plain ASGI: the tenant id must reach the endpoint."""
    client, _ = client_and_reader

    response = client.get(
        "/sales/S-1007",
        headers={"X-Tenant-Id": "dukawala-42", "Idempotency-Key": "key-abc"},
    )

    assert response.json()["tenant_id"] == "dukawala-42"
    assert response.json()["idempotency_key"] == "key-abc"


def test_context_does_not_leak_between_requests(client_and_reader):
    client, _ = client_and_reader

    client.get("/sales/S-1007", headers={"X-Tenant-Id": "dukawala-42"})
    response = client.get("/sales/S-1008")

    assert response.json()["tenant_id"] is None


def test_route_label_is_parameterised_not_the_concrete_path(client_and_reader):
    """A raw path would create one Prometheus series per sale id."""
    client, reader = client_and_reader
    client.get("/sales/S-1007")

    (point,) = data_points(reader, "pos_requests_total")
    assert point.attributes["route"] == "/sales/{sale_id}"
    assert point.attributes["method"] == "GET"
    assert point.attributes["status"] == "2xx"


def test_probe_traffic_is_not_counted(client_and_reader):
    """Counting probes would inflate every SLI denominator."""
    client, reader = client_and_reader
    client.get("/health")

    assert data_points(reader, "pos_requests_total") == []


def test_unhandled_exceptions_are_counted_as_server_errors(client_and_reader):
    """An uncounted failure is invisible to the error budget."""
    client, reader = client_and_reader
    response = client.get("/boom")

    assert response.status_code == 500
    (point,) = data_points(reader, "pos_requests_total")
    assert point.attributes["status"] == "5xx"
    assert point.value == 1


def test_duration_is_recorded(client_and_reader):
    client, reader = client_and_reader
    client.get("/sales/S-1007")

    (point,) = data_points(reader, "pos_request_duration_seconds")
    assert point.count == 1
    assert point.sum >= 0
    assert "status" not in point.attributes


def test_traced_opens_a_recording_span():
    with traced("payments.stk_push", amount_minor=150000) as span:
        assert span.get_span_context().is_valid
        assert trace.get_current_span() is span


def test_traced_does_not_swallow_exceptions():
    with pytest.raises(RuntimeError):
        with traced("payments.stk_push"):
            raise RuntimeError("daraja timeout")
