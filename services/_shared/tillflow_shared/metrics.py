"""Metric instruments, named as ADR-008 specifies.

The RED pair is what every per-service SLI in ``slo-error-budgets.md`` is measured
against, so the names and labels must match across all five services for one dashboard
query to work everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

from opentelemetry.metrics import Counter, Histogram, Meter


@dataclass(frozen=True)
class RedMetrics:
    """Request-rate, error-rate and duration instruments for one service."""

    requests_total: Counter
    request_duration_seconds: Histogram


def build_red_metrics(service_name: str, meter: Meter) -> RedMetrics:
    """Create this service's RED instruments."""
    return RedMetrics(
        requests_total=meter.create_counter(
            name=f"{service_name}_requests_total",
            description="Completed HTTP requests, by route, method and status class.",
            unit="1",
        ),
        request_duration_seconds=meter.create_histogram(
            name=f"{service_name}_request_duration_seconds",
            description="Wall-clock duration of completed HTTP requests.",
            unit="s",
        ),
    )


def business_counter(name: str, description: str) -> Counter:
    """A domain counter such as ``payments_stk_initiated_total``.

    Exposed so a service never touches the meter provider directly.
    """
    from tillflow_shared.telemetry import get_meter

    return get_meter().create_counter(name=name, description=description, unit="1")
