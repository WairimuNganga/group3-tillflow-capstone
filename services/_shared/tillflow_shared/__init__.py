"""Shared telemetry for every TillFlow service (ADR-008).

    from tillflow_shared import setup_telemetry, get_logger

    setup_telemetry("pos")
    log = get_logger(__name__)

HTTP services also wire ``tillflow_shared.middleware``. It is not imported here
because it needs the ``http`` extra, which the commission worker does not install.
"""

from tillflow_shared.context import get_idempotency_key, get_tenant_id, request_context
from tillflow_shared.logging import get_logger
from tillflow_shared.metrics import business_counter
from tillflow_shared.redaction import hash_msisdn, redact
from tillflow_shared.telemetry import (
    get_meter,
    get_tracer,
    setup_telemetry,
    shutdown_telemetry,
)

__all__ = [
    "business_counter",
    "get_idempotency_key",
    "get_logger",
    "get_meter",
    "get_tenant_id",
    "get_tracer",
    "hash_msisdn",
    "redact",
    "request_context",
    "setup_telemetry",
    "shutdown_telemetry",
]
