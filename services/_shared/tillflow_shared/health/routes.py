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
    """Standard ``/health`` (liveness) and ``/ready`` (readiness) endpoints.

    ``/ready`` returns 503, not just a JSON body, when not ready — ALB/ECS target
    health checks read the status code, not the body.
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
                # A failing probe means not-ready, not an unhandled 500.
                _log.exception("ready_check raised; reporting not_ready")
                is_ready = False

            if not is_ready:
                response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
                return {"status": "not_ready", "service": service_name}

        return {"status": "ready", "service": service_name}

    return router
