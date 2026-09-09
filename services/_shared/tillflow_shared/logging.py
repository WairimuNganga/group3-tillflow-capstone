"""Structured JSON logging with trace correlation.

ADR-008 fixes the fields as ``ts, level, service, trace_id, span_id, tenant_id, msg``.
The trace and span ids are what let a log line and an X-Ray trace describe the same
request. A service author writes ``log.info("sale created", extra={"sale_id": id})``;
every other field is filled in here.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace

from tillflow_shared.context import get_tenant_id
from tillflow_shared.redaction import redact

DEFAULT_LOG_LEVEL = "INFO"

# Attributes the stdlib sets on every record. Anything else arrived via ``extra=``.
# ``color_message`` is uvicorn's ANSI-coloured duplicate of its own message.
_STANDARD_RECORD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "color_message",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def _timestamp(created: float) -> str:
    """RFC 3339 in UTC, millisecond precision."""
    moment = datetime.fromtimestamp(created, tz=UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


class JsonFormatter(logging.Formatter):
    """Renders one log record as a single line of JSON."""

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": _timestamp(record.created),
            "level": record.levelname.lower(),
            "service": self.service_name,
        }

        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            payload["trace_id"] = f"{span_context.trace_id:032x}"
            payload["span_id"] = f"{span_context.span_id:016x}"

        payload["tenant_id"] = get_tenant_id()
        payload["msg"] = record.getMessage()
        payload["logger"] = record.name

        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            payload["error"] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc_value) if exc_value else None,
                "stack": self.formatException(record.exc_info),
            }

        # Last step, so it also covers the message and anything passed via ``extra=``.
        return json.dumps(redact(payload), default=str, separators=(",", ":"))


def configure_logging(service_name: str, level: str | None = None) -> None:
    """Point the root logger at stdout with the JSON formatter.

    Called by ``setup_telemetry``. Existing handlers are replaced rather than added
    to, because uvicorn installs its own on import and would otherwise emit every line
    twice.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service_name))

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel((level or DEFAULT_LOG_LEVEL).upper())

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    """A standard library logger. Emits JSON once ``setup_telemetry`` has run."""
    return logging.getLogger(name)
