from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TelemetryHandle:
    """Placeholder handle returned by ``init_telemetry`` until OTel wiring lands."""

    service_name: str
    money_path: bool


def init_telemetry(service_name: str, *, money_path: bool = False) -> TelemetryHandle:
    """Initialize tracing, metrics, and structured logging ([ADR-008]).

    Minage owns the full OpenTelemetry SDK + ADOT sidecar export implementation.
    """
    return TelemetryHandle(service_name=service_name, money_path=money_path)


def log_fields(**kwargs: Any) -> dict[str, Any]:
    """Structured log field helper stub — replace with JSON logger integration."""
    return dict(kwargs)
