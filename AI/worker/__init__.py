"""Analysis worker process package."""

from common import create_health_app

app = create_health_app("worker")

__all__ = ["app"]
