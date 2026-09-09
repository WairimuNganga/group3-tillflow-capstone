import logging
from collections.abc import Callable

from fastapi import APIRouter, Response, status

_log = logging.getLogger(__name__)


def create_health_router(
    *,
    service_name: str,
    git_sha: str = "unknown",
    ready_check: Callable[[], bool] | None = None,
) -> APIRouter:
    """Standard ``/health`` and ``/ready`` endpoints for the golden path.

    ``/health`` is liveness only — it must stay cheap and dependency-free, since the
    Docker/ECS healthcheck (``Dockerfile.base``) and any container-restart policy key
    off it. ``/ready`` is what an ALB target group or ECS service's own health check
    should point at instead: it answers "can this task take traffic right now", which
    ``ready_check`` lets a service wire up to its own DB-connection-pool state etc.

    The status *code*, not just the body, is what a target-group health check reads —
    almost nothing checking HTTP health parses a JSON body. A not-ready response that
    still returns 200 is invisible to ALB/ECS and defeats the point of a readiness
    probe, so this returns 503 in that case.
    """
    router = APIRouter(tags=["health"])

    @router.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": service_name,
            "git_sha": git_sha,
        }

    @router.get("/ready")
    def ready(response: Response) -> dict[str, str]:
        if ready_check is not None:
            try:
                is_ready = ready_check()
            except Exception:
                # A readiness probe that throws (a DB ping mid-outage, say) means
                # "not ready", not "crash the health endpoint into a 500". The
                # exception is still visible in logs/traces — just not as an
                # unhandled 500 from this route.
                _log.exception("ready_check raised; reporting not_ready")
                is_ready = False

            if not is_ready:
                response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
                return {"status": "not_ready", "service": service_name}

        return {"status": "ready", "service": service_name}

    return router
