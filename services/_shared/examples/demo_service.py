"""Development-only service that exercises the shared telemetry library.

Run it against the stack in ``services/_shared/local/`` to see a JSON log line with a
real trace id, a span in Jaeger, and the RED metrics increment in Prometheus, without
any of the real services existing yet. Delete it once POS and Payments are real.

Named ``payments`` so the money-path sampling rule applies and every request produces
a trace. Probes come from the shared health router, so this also demonstrates that the
middleware excludes them from the RED metrics.
"""

import os

from fastapi import FastAPI
from pydantic import BaseModel

from tillflow_shared import get_logger, setup_telemetry
from tillflow_shared.health import create_health_router
from tillflow_shared.otel import business_counter
from tillflow_shared.otel.middleware import instrument_fastapi, traced

setup_telemetry("payments")

log = get_logger(__name__)
app = FastAPI(title="TillFlow telemetry demo")
app.include_router(
    create_health_router(
        service_name="payments",
        git_sha=os.getenv("GIT_COMMIT_SHA", "unknown"),
    )
)
instrument_fastapi(app, service_name="payments")

stk_initiated = business_counter(
    "payments_stk_initiated_total",
    "STK push requests handed to the M-Pesa adapter.",
)


class StkRequest(BaseModel):
    amount_minor: int
    attendant_msisdn: str


@app.post("/demo/stk")
def demo_stk(request: StkRequest) -> dict[str, object]:
    """Passes a raw MSISDN into a log call to show that redaction is central."""
    log.info(
        "stk push requested for %s",
        request.attendant_msisdn,
        extra={"amount_minor": request.amount_minor},
    )

    with traced("payments.stk_push", amount_minor=request.amount_minor) as span:
        stk_initiated.add(1, {"result": "accepted"})
        log.info("stk push accepted", extra={"amount_minor": request.amount_minor})
        trace_id = f"{span.get_span_context().trace_id:032x}"

    return {"status": "pending", "trace_id": trace_id}


@app.get("/demo/boom")
def demo_boom() -> None:
    """Produces a 5xx so the error path shows up in the metrics and the trace."""
    with traced("payments.stk_push"):
        raise RuntimeError("daraja timeout")
