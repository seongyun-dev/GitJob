import asyncio

import httpx
import pytest
from fastapi import FastAPI

from collector import app as collector_app
from worker import app as worker_app


@pytest.mark.parametrize(
    ("app", "service_name"),
    [
        (collector_app, "collector"),
        (worker_app, "worker"),
    ],
)
def test_health_reports_only_process_liveness(
    app: FastAPI,
    service_name: str,
) -> None:
    async def get_health() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get("/health")

    response = asyncio.run(get_health())

    assert response.status_code == 200
    assert response.json() == {
        "status": "alive",
        "service": service_name,
    }
