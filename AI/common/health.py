"""Process-liveness HTTP application shared by collector and worker."""

from typing import TypedDict

from fastapi import FastAPI


class HealthResponse(TypedDict):
    """Response returned by the process-liveness endpoint."""

    status: str
    service: str


def create_health_app(service_name: str) -> FastAPI:
    """Create a minimal liveness application for one AI process."""
    app = FastAPI(
        title=f"GitJob {service_name}",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/health")
    def health() -> HealthResponse:
        return {
            "status": "alive",
            "service": service_name,
        }

    return app
