"""OpenTelemetry instrumentation — DRI: Minage ([ADR-008]).

    from tillflow_shared.otel import setup_telemetry, get_logger

    setup_telemetry("pos")
    log = get_logger(__name__)

``middleware`` and ``http_client`` are imported directly rather than re-exported here,
so a worker that serves no HTTP does not pull in the ASGI instrumentation.
"""

from tillflow_shared.otel.bootstrap import (
    get_meter,
    get_tracer,
    setup_telemetry,
    shutdown_telemetry,
)
from tillflow_shared.otel.context import (
    get_idempotency_key,
    get_tenant_id,
    request_context,
)
from tillflow_shared.otel.logging import get_logger
from tillflow_shared.otel.metrics import business_counter
from tillflow_shared.otel.pii import hash_msisdn, redact, redact_msisdn

__all__ = [
    "business_counter",
    "get_idempotency_key",
    "get_logger",
    "get_meter",
    "get_tenant_id",
    "get_tracer",
    "hash_msisdn",
    "redact",
    "redact_msisdn",
    "request_context",
    "setup_telemetry",
    "shutdown_telemetry",
]
