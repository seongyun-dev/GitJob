"""Collector process package."""

from common import create_health_app

app = create_health_app("collector")

__all__ = ["app"]
