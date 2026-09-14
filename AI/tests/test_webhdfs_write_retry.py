"""Bounded retry contract for the WebHDFS immutable write two-hop."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from common import webhdfs as webhdfs_module
from common.webhdfs import WebHdfsClient, WebHdfsError, WebHdfsResponse


BASE_URL = "http://hdfs-namenode:9870/webhdfs/v1"
REDIRECT = "http://hdfs-datanode:9864/webhdfs/v1/upload"
PATH = "/gitjob/raw/retry.json.gz"
CONTENT = b"payload"


def _boolean(value: bool) -> bytes:
    return json.dumps({"boolean": value}).encode()


@dataclass
class ScriptedTransport:
    """Minimal NameNode/DataNode fake with scripted CREATE/upload outcomes."""

    create_outcomes: list[Any] = field(default_factory=list)
    upload_outcomes: list[Any] = field(default_factory=list)
    existing: bool = False
    existing_content: bytes = CONTENT
    calls: list[tuple[str, str]] = field(default_factory=list)

    def request(
        self,
        method: str,
        url: str,
        *,
        body: object | None = None,
        timeout: float,
    ) -> WebHdfsResponse:
        assert timeout > 0
        self.calls.append((method, url))
        if url == REDIRECT:
            return self._next(
                self.upload_outcomes,
                WebHdfsResponse(201, {}, b""),
            )
        operation = url.rsplit("op=", 1)[1].split("&", 1)[0]
        if operation == "GETFILESTATUS":
            if self.existing:
                return WebHdfsResponse(200, {}, b'{"FileStatus":{}}')
            return WebHdfsResponse(404, {}, b'{"RemoteException":{}}')
        if operation == "OPEN":
            return WebHdfsResponse(200, {}, self.existing_content)
        if operation == "MKDIRS":
            return WebHdfsResponse(200, {}, _boolean(True))
        if operation == "CREATE":
            return self._next(
                self.create_outcomes,
                WebHdfsResponse(307, {"Location": REDIRECT}, b""),
            )
        if operation == "RENAME":
            return WebHdfsResponse(200, {}, _boolean(True))
        if operation == "DELETE":
            return WebHdfsResponse(200, {}, _boolean(True))
        raise AssertionError(f"unexpected WebHDFS operation: {operation}")

    @staticmethod
    def _next(outcomes: list[Any], default: WebHdfsResponse) -> WebHdfsResponse:
        if not outcomes:
            return default
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def operation_calls(self, operation: str) -> list[tuple[str, str]]:
        return [
            call
            for call in self.calls
            if f"op={operation}" in call[1]
        ]


def _client(transport: ScriptedTransport) -> WebHdfsClient:
    return WebHdfsClient(
        base_url=BASE_URL,
        transport=transport,
        timeout=1,
    )


def test_timeout_on_datanode_hop_retries_then_publishes_once(monkeypatch):
    monkeypatch.setattr(webhdfs_module.time, "sleep", lambda _: None)
    transport = ScriptedTransport(upload_outcomes=[TimeoutError("timed out")])

    assert _client(transport).store_immutable(PATH, CONTENT) == f"hdfs://{PATH}"
    assert len(transport.upload_outcomes) == 0
    assert len([url for _, url in transport.calls if url == REDIRECT]) == 2
    assert len(transport.operation_calls("RENAME")) == 1


def test_connection_refused_on_create_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(webhdfs_module.time, "sleep", lambda _: None)
    transport = ScriptedTransport(
        create_outcomes=[ConnectionRefusedError(111, "connection refused")]
    )

    _client(transport).store_immutable(PATH, CONTENT)

    assert len(transport.operation_calls("CREATE")) == 2
    assert len([url for _, url in transport.calls if url == REDIRECT]) == 1


def test_persistent_transient_failure_stops_at_max_attempts_and_cleans_temp(
    monkeypatch,
):
    monkeypatch.setattr(webhdfs_module.time, "sleep", lambda _: None)
    transport = ScriptedTransport(
        upload_outcomes=[TimeoutError("timed out")] * 3,
    )

    with pytest.raises(WebHdfsError, match="after 3 attempts"):
        _client(transport).store_immutable(PATH, CONTENT)

    assert len([url for _, url in transport.calls if url == REDIRECT]) == 3
    assert len(transport.operation_calls("DELETE")) == 1


def test_permanent_http_error_fails_without_retry(monkeypatch):
    monkeypatch.setattr(webhdfs_module.time, "sleep", lambda _: None)
    transport = ScriptedTransport(
        upload_outcomes=[WebHdfsResponse(403, {}, b"denied")],
    )

    with pytest.raises(WebHdfsError, match="HTTP 403"):
        _client(transport).store_immutable(PATH, CONTENT)

    assert len([url for _, url in transport.calls if url == REDIRECT]) == 1
    assert len(transport.operation_calls("DELETE")) == 1


def test_immutable_conflict_does_not_attempt_upload_or_retry(monkeypatch):
    monkeypatch.setattr(webhdfs_module.time, "sleep", lambda _: None)
    transport = ScriptedTransport(existing=True, existing_content=b"different")

    with pytest.raises(FileExistsError, match="immutable WebHDFS"):
        _client(transport).store_immutable(PATH, CONTENT)

    assert not [url for _, url in transport.calls if url == REDIRECT]
    assert not transport.operation_calls("DELETE")

def test_successful_write_creates_exactly_one_immutable_artifact(monkeypatch):
    monkeypatch.setattr(webhdfs_module.time, "sleep", lambda _: None)
    transport = ScriptedTransport()

    _client(transport).store_immutable(PATH, CONTENT)

    assert len([url for _, url in transport.calls if url == REDIRECT]) == 1
    assert len(transport.operation_calls("RENAME")) == 1
    assert not transport.operation_calls("DELETE")
