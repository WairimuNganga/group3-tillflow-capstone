"""TillFlow shared libraries — M-Pesa adapter, OTel instrumentation, health routes.

One subpackage per DRI, so two owners never edit the same file:

| Subpackage | DRI |
|---|---|
| ``tillflow_shared.mpesa`` | Hunter ([ADR-007]) |
| ``tillflow_shared.otel`` | Minage ([ADR-008]) |
| ``tillflow_shared.health`` | Wairimu (golden path) |

The most-used calls are re-exported here for convenience.
"""

from tillflow_shared.mpesa.factory import create_mpesa_adapter
from tillflow_shared.mpesa.settings import MpesaSettings
from tillflow_shared.otel import get_logger, setup_telemetry

__all__ = [
    "MpesaSettings",
    "create_mpesa_adapter",
    "get_logger",
    "setup_telemetry",
]
