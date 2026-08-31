"""Shared HTTP server startup for AI process entrypoints."""

import os

import uvicorn
from fastapi import FastAPI


def run_health_server(app: FastAPI) -> None:
    """Run one AI process health server with Compose-compatible defaults."""
    uvicorn.run(
        app,
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", "8080")),
    )
