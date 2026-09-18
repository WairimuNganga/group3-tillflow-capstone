import os

from fastapi import FastAPI
from tillflow_shared import setup_telemetry
from tillflow_shared.health import create_health_router
from tillflow_shared.idempotency import register_idempotency_handlers
from tillflow_shared.otel.middleware import instrument_fastapi

from payments import db
from payments.api import b2c_router, callbacks_router, reconcile_router, stk_router
from payments.config import settings

# Disable OTLP export in CI/unit tests unless a collector is running.
if "TILLFLOW_TELEMETRY_EXPORT" not in os.environ:
    os.environ.setdefault("TILLFLOW_TELEMETRY_EXPORT", "none")

setup_telemetry(settings.service_name)


def _ready_probe() -> bool:
    """Delegate through the module so tests can monkeypatch ``payments.db.is_db_ready``."""
    return db.is_db_ready()


app = FastAPI(title="TillFlow Payments", version="0.1.0")
register_idempotency_handlers(app)
app.include_router(
    create_health_router(
        service_name=settings.service_name,
        git_sha=settings.git_commit_sha,
        ready_check=_ready_probe,
    )
)
app.include_router(stk_router)
app.include_router(callbacks_router)
app.include_router(reconcile_router)
app.include_router(b2c_router)
instrument_fastapi(app, service_name=settings.service_name)
