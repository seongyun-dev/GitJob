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


# -- 기여 판정 스위치 --------------------------------------------------------


def test_the_flag_reads_false_as_false_not_as_a_nonempty_string(monkeypatch):
    """`bool(os.getenv(...))` 였다면 "false" 가 참이 된다.

    끄려고 넣은 값이 켜는 결과가 되면, 전체 히스토리 클론이 의도 없이 돌아간다.
    """
    from analysis.__main__ import _flag

    for off in ["false", "False", "0", "no", "off", " FALSE "]:
        monkeypatch.setenv("X_FLAG", off)
        assert _flag("X_FLAG", default=True) is False, off

    for on in ["true", "TRUE", "1", "yes", "on"]:
        monkeypatch.setenv("X_FLAG", on)
        assert _flag("X_FLAG", default=False) is True, on


def test_an_unset_or_unrecognised_flag_keeps_the_default(monkeypatch):
    from analysis.__main__ import _flag

    monkeypatch.delenv("X_FLAG", raising=False)
    assert _flag("X_FLAG", default=False) is False
    assert _flag("X_FLAG", default=True) is True

    monkeypatch.setenv("X_FLAG", "maybe")
    assert _flag("X_FLAG", default=False) is False


def test_attribution_and_history_are_one_switch(monkeypatch, tmp_path):
    """따로 켜게 두면 조용히 틀린 값이 나오는 설정이 만들어진다.

    blame 은 얕은 체크아웃에서 실패하지 않고 모든 줄을 tip 커밋에 돌린다. 기여
    판정만 켜고 히스토리를 끄면 그 결과가 그대로 저장된다. 그래서 스위치가 하나다.
    """
    import analysis.__main__ as entry

    monkeypatch.setenv("ANALYSIS_ATTRIBUTE_AUTHORS", "true")
    monkeypatch.setenv("ANALYSIS_WORK_ROOT", str(tmp_path))

    captured: dict = {}

    class SpyCloner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class ReadyClaims:
        def __init__(self, *args, **kwargs):
            pass

        def ready(self):
            return True

    monkeypatch.setattr(entry, "RepositoryCloner", SpyCloner)
    monkeypatch.setattr(entry, "ClaimStore", ReadyClaims)
    monkeypatch.setattr(entry, "AnalysisConsumer", lambda **kwargs: kwargs)
    monkeypatch.setattr(entry, "consumer_from_env", lambda *a, **k: object())
    monkeypatch.setattr(entry, "transport_from_env", lambda *a, **k: object())
    monkeypatch.setattr(entry, "dsn_from_env", lambda: "postgresql://x/y")
    monkeypatch.setattr(entry, "verify_grammars", lambda: None)

    built = entry.build()

    assert captured["with_history"] is True, "기여 판정을 켜면 히스토리도 켜져야 한다"
    assert built["attribute_authors"] is True


def test_attribution_is_off_by_default(monkeypatch, tmp_path):
    # 전체 히스토리 클론은 비싸다. 개인 판정을 안 쓰는 배포가 그 값을 내면 안 된다.
    import analysis.__main__ as entry

    monkeypatch.delenv("ANALYSIS_ATTRIBUTE_AUTHORS", raising=False)
    monkeypatch.setenv("ANALYSIS_WORK_ROOT", str(tmp_path))

    captured: dict = {}

    class SpyCloner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class ReadyClaims:
        def __init__(self, *args, **kwargs):
            pass

        def ready(self):
            return True

    monkeypatch.setattr(entry, "RepositoryCloner", SpyCloner)
    monkeypatch.setattr(entry, "ClaimStore", ReadyClaims)
    monkeypatch.setattr(entry, "AnalysisConsumer", lambda **kwargs: kwargs)
    monkeypatch.setattr(entry, "consumer_from_env", lambda *a, **k: object())
    monkeypatch.setattr(entry, "transport_from_env", lambda *a, **k: object())
    monkeypatch.setattr(entry, "dsn_from_env", lambda: "postgresql://x/y")
    monkeypatch.setattr(entry, "verify_grammars", lambda: None)

    built = entry.build()

    assert captured["with_history"] is False
    assert built["attribute_authors"] is False


def test_private_repository_broker_is_off_by_default(monkeypatch):
    from analysis.__main__ import credential_broker_from_env

    monkeypatch.delenv("ANALYSIS_PRIVATE_REPOSITORIES_ENABLED", raising=False)

    assert credential_broker_from_env() is None


def test_private_repository_broker_requires_both_endpoint_and_service_token(monkeypatch):
    from analysis.__main__ import credential_broker_from_env

    monkeypatch.setenv("ANALYSIS_PRIVATE_REPOSITORIES_ENABLED", "true")
    monkeypatch.delenv("ANALYSIS_CREDENTIAL_BROKER_URL", raising=False)
    monkeypatch.delenv("ANALYSIS_WORKER_SERVICE_TOKEN", raising=False)

    with pytest.raises(SystemExit, match="ANALYSIS_CREDENTIAL_BROKER_URL"):
        credential_broker_from_env()


def test_private_repository_broker_uses_configured_timeout(monkeypatch):
    from analysis.__main__ import credential_broker_from_env

    monkeypatch.setenv("ANALYSIS_PRIVATE_REPOSITORIES_ENABLED", "true")
    monkeypatch.setenv(
        "ANALYSIS_CREDENTIAL_BROKER_URL",
        "http://backend:8080/internal/v1/repository-analysis/credentials",
    )
    monkeypatch.setenv("ANALYSIS_WORKER_SERVICE_TOKEN", "service-token")
    monkeypatch.setenv("ANALYSIS_CREDENTIAL_BROKER_TIMEOUT_SECONDS", "7")

    broker = credential_broker_from_env()

    assert broker is not None
    assert broker.timeout_seconds == 7
