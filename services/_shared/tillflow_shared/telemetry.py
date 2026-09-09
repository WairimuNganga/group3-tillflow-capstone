"""One-call telemetry bootstrap.

    setup_telemetry("pos")

Installs the tracer provider with this service's ADR-008 sampling policy, the meter
provider, and JSON logging, and points both exporters at the ADOT collector. Per
ADR-008 no service talks to Amazon Managed Prometheus or X-Ray directly, which is why
the default endpoint is on localhost: in ECS the collector is a sidecar in the same
task.
"""

from __future__ import annotations

import atexit
import os

from opentelemetry import metrics, trace
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from tillflow_shared.logging import configure_logging, get_logger
from tillflow_shared.sampling import sampler_for_service

DEFAULT_OTLP_ENDPOINT = "http://localhost:4317"

# ``otlp`` everywhere real; ``none`` in unit tests and CI, which must not require a
# running collector. Spans are still created under ``none``, so log correlation is
# genuinely exercised — they are simply never exported.
_EXPORT_MODE_ENV_VAR = "TILLFLOW_TELEMETRY_EXPORT"

_METRIC_INTERVAL_ENV_VAR = "TILLFLOW_METRIC_EXPORT_INTERVAL_MS"
_DEFAULT_METRIC_INTERVAL_MS = 15_000

_configured = False


def _resource(service_name: str, extra_attributes: dict[str, str] | None) -> Resource:
    """Identity attached to every span and metric this process emits.

    ``Resource.create`` also folds in ``OTEL_RESOURCE_ATTRIBUTES``, which is the
    contract with the shared Dockerfile: the image supplies environment-level
    attributes and this package supplies service-level ones. ``service.version``
    carries the commit SHA so a running task can be matched to a pipeline run.
    """
    attributes: dict[str, str] = {
        SERVICE_NAME: service_name,
        SERVICE_VERSION: os.getenv("GIT_COMMIT_SHA", "unknown"),
        "deployment.environment.name": os.getenv("TILLFLOW_ENVIRONMENT", "local"),
    }
    if extra_attributes:
        attributes.update(extra_attributes)
    return Resource.create(attributes)


def _install_tracing(service_name: str, resource: Resource, export: bool, endpoint: str) -> None:
    provider = TracerProvider(resource=resource, sampler=sampler_for_service(service_name))
    if export:
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=not endpoint.startswith("https://"))
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def _install_metrics(resource: Resource, export: bool, endpoint: str) -> None:
    readers = []
    if export:
        exporter = OTLPMetricExporter(
            endpoint=endpoint, insecure=not endpoint.startswith("https://")
        )
        interval_ms = int(os.getenv(_METRIC_INTERVAL_ENV_VAR, _DEFAULT_METRIC_INTERVAL_MS))
        readers.append(PeriodicExportingMetricReader(exporter, export_interval_millis=interval_ms))
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=readers))


def setup_telemetry(
    service_name: str,
    *,
    otlp_endpoint: str | None = None,
    log_level: str | None = None,
    resource_attributes: dict[str, str] | None = None,
) -> None:
    """Configure tracing, metrics and JSON logging. Call once, at startup.

    Safe to call twice; the second call is ignored rather than registering a duplicate
    set of exporters.
    """
    global _configured
    if _configured:
        return

    export = os.getenv(_EXPORT_MODE_ENV_VAR, "otlp").lower() != "none"
    endpoint = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or DEFAULT_OTLP_ENDPOINT
    resource = _resource(service_name, resource_attributes)

    # Pinned rather than left to OTEL_PROPAGATORS: if two services disagree on the
    # wire format, cross-service traces break silently.
    set_global_textmap(
        CompositePropagator([TraceContextTextMapPropagator(), W3CBaggagePropagator()])
    )

    _install_tracing(service_name, resource, export, endpoint)
    _install_metrics(resource, export, endpoint)
    configure_logging(service_name, log_level or os.getenv("LOG_LEVEL"))

    _configured = True
    atexit.register(shutdown_telemetry)
    get_logger(__name__).info(
        "telemetry configured",
        extra={"otlp_endpoint": endpoint if export else None},
    )


def shutdown_telemetry() -> None:
    """Flush pending spans and metrics.

    Without this a short-lived task — the commission worker's daily run especially —
    can drop the batch describing its final and most interesting moments.
    """
    tracer_provider = trace.get_tracer_provider()
    if isinstance(tracer_provider, TracerProvider):
        tracer_provider.shutdown()

    meter_provider = metrics.get_meter_provider()
    if isinstance(meter_provider, MeterProvider):
        meter_provider.shutdown()


def get_tracer(name: str | None = None) -> trace.Tracer:
    return trace.get_tracer(name or "tillflow_shared")


def get_meter(name: str | None = None) -> metrics.Meter:
    return metrics.get_meter(name or "tillflow_shared")
