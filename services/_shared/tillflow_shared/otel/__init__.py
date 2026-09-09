"""OpenTelemetry bootstrap — owned by Minage ([ADR-008])."""

from tillflow_shared.otel.bootstrap import TelemetryHandle, init_telemetry

__all__ = ["TelemetryHandle", "init_telemetry"]
