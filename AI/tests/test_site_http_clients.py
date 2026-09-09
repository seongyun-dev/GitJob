"""Retry classification in the two collectors that keep their own HTTP client.

S15P21E102-173 widened the shared `PoliteHttpClient` so a truncated chunked
response is retried instead of ending the whole round. Worknet and JobKorea
were not on that client — they carry their own, and both caught only
`HTTPError` and `URLError`, so the same three exceptions escaped `read()`:

    http.client.IncompleteRead   HTTPException only. Not OSError, not URLError
    TimeoutError                 an OSError, but not a URLError
    plain OSError                connection reset

`URLError` subclasses `OSError`, not the reverse, which is why `except
URLError` looked like it covered transport errors and did not.

Worknet matters most: 5,648 postings across 15 rounds, more than any other
collector, and a round that dies takes the day's postings with it.

`urlopen` is patched in each module's namespace, so these run offline.
"""

from __future__ import annotations

from http.client import IncompleteRead
from typing import Self
from urllib.error import HTTPError, URLError

import pytest

from JobKorea_Collector_V1 import client as jobkorea_module
from JobKorea_Collector_V1.client import (
    JobKoreaBlockedError,
    JobKoreaHttpClient,
    JobKoreaHttpError,
)
from Worknet_Collector_V1 import client as worknet_module
from Worknet_Collector_V1.client import (
    WorknetBlockedError,
    WorknetHttpClient,
    WorknetHttpError,
)


class _FakeResponse:
    """Minimal stand-in for what `urlopen` yields."""

    def __init__(self, body: bytes | Exception, charset: str = "utf-8") -> None:
        self._body = body
        self._charset = charset

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    @property
    def headers(self):
        charset = self._charset

        class _Headers:
            @staticmethod
            def get_content_charset():
                return charset

            @staticmethod
            def get(_name, default=None):
                return default

        return _Headers()

    def read(self) -> bytes:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _patch(monkeypatch, module, outcomes: list[bytes | Exception]) -> list[str]:
    """Serve one outcome per attempt. Returns the call counter.

    An `IncompleteRead` is raised from `read()` rather than from `urlopen`,
    because that is where it actually happens — the connection opens fine and
    the body arrives short.
    """

    calls: list[str] = []

    def fake_urlopen(request, timeout=None):
        calls.append(request.full_url)
        outcome = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
        if isinstance(outcome, Exception) and not isinstance(outcome, IncompleteRead):
            raise outcome
        return _FakeResponse(outcome)

    monkeypatch.setattr(module, "urlopen", fake_urlopen)
    # No real sleeping between attempts.
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    return calls


# --- Worknet: the collector with the most to lose ---------------------------


def test_worknet_retries_an_incomplete_read(monkeypatch):
    """A truncated body must not end the round.

    Worknet runs twice a day and holds 5,648 postings; a round that dies loses
    that window entirely, and the window cannot be collected again once the
    postings close.
    """

    calls = _patch(
        monkeypatch,
        worknet_module,
        [IncompleteRead(b"half", 27065), b"<html>full</html>"],
    )

    body = WorknetHttpClient(backoff_base_seconds=0).get("/detail")

    assert body == "<html>full</html>"
    assert len(calls) == 2


def test_worknet_retries_a_timeout_during_read(monkeypatch):
    """`TimeoutError` is an `OSError` but not a `URLError`."""

    calls = _patch(monkeypatch, worknet_module, [TimeoutError("read timed out"), b"ok"])

    assert WorknetHttpClient(backoff_base_seconds=0).get("/x") == "ok"
    assert len(calls) == 2


def test_worknet_retries_a_plain_oserror(monkeypatch):
    calls = _patch(monkeypatch, worknet_module, [OSError("connection reset"), b"ok"])

    assert WorknetHttpClient(backoff_base_seconds=0).get("/x") == "ok"
    assert len(calls) == 2


def test_worknet_exhausted_retries_raise_the_site_error(monkeypatch):
    """Callers catch `WorknetHttpError`; an `IncompleteRead` reaching them does not."""

    calls = _patch(monkeypatch, worknet_module, [IncompleteRead(b"half", 10)])

    with pytest.raises(WorknetHttpError, match="failed after 3 attempts"):
        WorknetHttpClient(backoff_base_seconds=0).get("/x")

    assert len(calls) == 3


def test_worknet_does_not_mistake_a_truncated_read_for_a_block(monkeypatch):
    """Classifying it as blocked would stop the whole site for the round."""

    _patch(monkeypatch, worknet_module, [IncompleteRead(b"half", 10)])

    with pytest.raises(WorknetHttpError) as caught:
        WorknetHttpClient(backoff_base_seconds=0).get("/x")
    assert not isinstance(caught.value, WorknetBlockedError)


def test_worknet_block_page_still_stops_the_site(monkeypatch):
    """The widened `except` must not swallow the block page.

    `WorknetBlockedError` is raised inside the same `try` as `read()`. It
    subclasses `RuntimeError`, not `OSError`, so the new tuple does not catch
    it — this test is what keeps that true.
    """

    calls = _patch(monkeypatch, worknet_module, ["<html>자동입력 방지".encode()])

    with pytest.raises(WorknetBlockedError, match="access-block"):
        WorknetHttpClient(backoff_base_seconds=0).get("/x")

    # Raised on the first attempt, not retried three times.
    assert len(calls) == 1


def test_worknet_refusal_status_is_not_retried(monkeypatch):
    """403 means retrying gets the IP banned."""

    calls = _patch(
        monkeypatch,
        worknet_module,
        [HTTPError("https://www.work24.go.kr/x", 403, "Forbidden", {}, None)],
    )

    with pytest.raises(WorknetBlockedError, match="refused"):
        WorknetHttpClient(backoff_base_seconds=0).get("/x")

    assert len(calls) == 1


def test_worknet_still_retries_a_url_error(monkeypatch):
    """The classification that already worked must keep working."""

    calls = _patch(monkeypatch, worknet_module, [URLError("reset"), b"ok"])

    assert WorknetHttpClient(backoff_base_seconds=0).get("/x") == "ok"
    assert len(calls) == 2


def test_worknet_retryable_status_is_retried(monkeypatch):
    calls = _patch(
        monkeypatch,
        worknet_module,
        [HTTPError("https://www.work24.go.kr/x", 503, "Unavailable", {}, None), b"ok"],
    )

    assert WorknetHttpClient(backoff_base_seconds=0).get("/x") == "ok"
    assert len(calls) == 2


def test_worknet_non_retryable_status_raises_at_once(monkeypatch):
    calls = _patch(
        monkeypatch,
        worknet_module,
        [HTTPError("https://www.work24.go.kr/x", 404, "Not Found", {}, None)],
    )

    with pytest.raises(WorknetHttpError, match="HTTP 404"):
        WorknetHttpClient(backoff_base_seconds=0).get("/x")

    assert len(calls) == 1


# --- JobKorea: same defect, same fix ----------------------------------------


def test_jobkorea_retries_an_incomplete_read(monkeypatch):
    calls = _patch(
        monkeypatch,
        jobkorea_module,
        [IncompleteRead(b"half", 27065), b"<html>full</html>"],
    )

    body = JobKoreaHttpClient().get("/detail")

    assert "full" in body
    assert len(calls) == 2


def test_jobkorea_retries_a_timeout_during_read(monkeypatch):
    calls = _patch(
        monkeypatch, jobkorea_module, [TimeoutError("read timed out"), b"ok"]
    )

    assert JobKoreaHttpClient().get("/x") == "ok"
    assert len(calls) == 2


def test_jobkorea_exhausted_retries_raise_the_site_error(monkeypatch):
    calls = _patch(monkeypatch, jobkorea_module, [IncompleteRead(b"half", 10)])

    with pytest.raises(JobKoreaHttpError, match="failed after 3 attempts"):
        JobKoreaHttpClient().get("/x")

    assert len(calls) == 3


def test_jobkorea_block_page_still_stops_the_site(monkeypatch):
    calls = _patch(monkeypatch, jobkorea_module, ["<html>자동입력 방지".encode()])

    with pytest.raises(JobKoreaBlockedError):
        JobKoreaHttpClient().get("/x")

    assert len(calls) == 1


def test_jobkorea_refusal_status_is_not_retried(monkeypatch):
    calls = _patch(
        monkeypatch,
        jobkorea_module,
        [HTTPError("https://www.jobkorea.co.kr/x", 403, "Forbidden", {}, None)],
    )

    with pytest.raises(JobKoreaBlockedError, match="refused"):
        JobKoreaHttpClient().get("/x")

    assert len(calls) == 1


def test_jobkorea_bytes_path_is_also_covered(monkeypatch):
    """`get_bytes` exists for OCR and goes through the same retry loop."""

    calls = _patch(
        monkeypatch,
        jobkorea_module,
        [IncompleteRead(b"half", 10), b"\x89PNG"],
    )

    content = JobKoreaHttpClient().get_bytes("/image")

    assert content == b"\x89PNG"
    assert len(calls) == 2
