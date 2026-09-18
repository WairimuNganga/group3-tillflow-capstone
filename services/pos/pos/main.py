import os

from fastapi import FastAPI
from tillflow_shared import setup_telemetry
from tillflow_shared.health import create_health_router
from tillflow_shared.otel.middleware import instrument_fastapi

from pos import db
from pos.api import internal_router, sales_router, tenants_router
from pos.config import settings

# Disable OTLP export in CI/unit tests unless a collector is running.
if "TILLFLOW_TELEMETRY_EXPORT" not in os.environ:
    os.environ.setdefault("TILLFLOW_TELEMETRY_EXPORT", "none")

setup_telemetry(settings.service_name)


def _ready_probe() -> bool:
    """Delegate through the module so tests can monkeypatch ``pos.db.is_db_ready``."""
    return db.is_db_ready()


app = FastAPI(title="TillFlow POS", version="0.1.0")
app.include_router(
    create_health_router(
        service_name=settings.service_name,
        git_sha=settings.git_commit_sha,
        ready_check=_ready_probe,
    )
)
app.include_router(tenants_router)
app.include_router(sales_router)
app.include_router(internal_router)
instrument_fastapi(app, service_name=settings.service_name)
