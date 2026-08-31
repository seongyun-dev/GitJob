import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

AI_ROOT = Path(__file__).resolve().parents[1]


def find_free_port() -> int:
    with socket.socket() as server_socket:
        server_socket.bind(("127.0.0.1", 0))
        return server_socket.getsockname()[1]


def wait_for_health(
    process: subprocess.Popen[str],
    port: int,
    service_name: str,
) -> None:
    deadline = time.monotonic() + 10
    health_url = f"http://127.0.0.1:{port}/health"

    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            pytest.fail(
                f"{service_name} exited before becoming healthy "
                f"(code={process.returncode})\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )

        try:
            with urllib.request.urlopen(health_url, timeout=1) as response:
                payload = json.load(response)
            assert response.status == 200
            assert payload == {
                "status": "alive",
                "service": service_name,
            }
            return
        except (ConnectionError, TimeoutError, urllib.error.URLError):
            time.sleep(0.1)

    pytest.fail(f"{service_name} did not become healthy within 10 seconds")


@pytest.mark.parametrize("service_name", ["collector", "worker"])
def test_module_entrypoint_starts_health_server(service_name: str) -> None:
    port = find_free_port()
    environment = os.environ.copy()
    environment.update(
        {
            "APP_HOST": "127.0.0.1",
            "APP_PORT": str(port),
            "PYTHONUNBUFFERED": "1",
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", service_name],
        cwd=AI_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        wait_for_health(process, port, service_name)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
