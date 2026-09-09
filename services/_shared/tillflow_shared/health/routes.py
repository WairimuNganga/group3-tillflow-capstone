from typing import Callable

from fastapi import APIRouter


def create_health_router(
    *,
    service_name: str,
    git_sha: str = "unknown",
    ready_check: Callable[[], bool] | None = None,
) -> APIRouter:
    """Standard ``/health`` and ``/ready`` endpoints for the golden path."""
    router = APIRouter(tags=["health"])

    @router.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": service_name,
            "git_sha": git_sha,
        }

    @router.get("/ready")
    def ready() -> dict[str, str]:
        if ready_check is not None and not ready_check():
            return {"status": "not_ready", "service": service_name}
        return {"status": "ready", "service": service_name}

    return router
