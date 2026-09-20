import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from tillflow_shared import setup_telemetry
from tillflow_shared.health import create_health_router
from tillflow_shared.otel.middleware import instrument_fastapi

from commission import db
from commission.api import router as internal_router
from commission.config import settings
from commission.deps import get_close_service, get_payments_client, get_payout_service, get_queue
from commission.worker.loop import WorkerLoop

if "TILLFLOW_TELEMETRY_EXPORT" not in os.environ:
    os.environ.setdefault("TILLFLOW_TELEMETRY_EXPORT", "none")

setup_telemetry(settings.service_name)
_log = logging.getLogger(__name__)


def _ready_probe() -> bool:
    if not settings.database_url:
        return True
    return db.is_db_ready()


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker_task: asyncio.Task | None = None
    loop: WorkerLoop | None = None
    if settings.worker_enabled:
        close_svc = get_close_service(session=None)
        payout_svc = get_payout_service(session=None)
        get_payments_client()
        loop = WorkerLoop(
            queue=get_queue(),
            close_service=close_svc,
            payout_service=payout_svc,
        )
        worker_task = asyncio.create_task(loop.run_forever(), name="commission-worker")
        _log.info("commission SQS/in-memory worker task started")
    try:
        yield
    finally:
        if loop is not None:
            loop.request_stop()
        if worker_task is not None:
            worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task


app = FastAPI(title="TillFlow Commission", version="0.1.0", lifespan=lifespan)
app.include_router(
    create_health_router(
        service_name=settings.service_name,
        git_sha=settings.git_commit_sha,
        ready_check=_ready_probe,
    )
)
app.include_router(internal_router)
instrument_fastapi(app, service_name=settings.service_name)
