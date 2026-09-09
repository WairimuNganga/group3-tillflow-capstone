"""Trace sampling policy (ADR-008).

Money-path services are sampled at 100%: they are low volume, and ADR-004's required
evidence is a complete trace that cannot be recovered once sampled away. Read-heavy
services are sampled at 10%.

Two gaps that need an ADR-008 amendment are recorded in ``local/README.md``: money-path
services ignore the parent decision, and the "always sample errors" rule lives in the
collector rather than here.
"""

from __future__ import annotations

import os

from opentelemetry.sdk.trace.sampling import (
    ALWAYS_ON,
    ParentBased,
    Sampler,
    TraceIdRatioBased,
)

MONEY_PATH_SERVICES = frozenset({"payments", "commission"})
MONEY_PATH_RATIO = 1.0
READ_PATH_RATIO = 0.1

_RATIO_ENV_VAR = "TILLFLOW_TRACE_SAMPLE_RATIO"


def ratio_for_service(service_name: str) -> float:
    """The head-sampling ratio for this service.

    The env override lets a k6 run or an incident investigation raise the rate on a
    read path without a code change.
    """
    override = os.getenv(_RATIO_ENV_VAR)
    if override:
        return max(0.0, min(1.0, float(override)))
    return MONEY_PATH_RATIO if service_name in MONEY_PATH_SERVICES else READ_PATH_RATIO


def sampler_for_service(service_name: str) -> Sampler:
    """The sampler this service installs at startup.

    Money-path services are unconditional and deliberately not parent-based: a sale
    starts in ``pos`` at 10%, so deferring to the parent would leave 90% of payments
    with no trace at all.
    """
    ratio = ratio_for_service(service_name)
    if ratio >= 1.0:
        return ALWAYS_ON
    return ParentBased(root=TraceIdRatioBased(ratio))
