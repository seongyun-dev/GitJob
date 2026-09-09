"""Retry and refusal behaviour of the shared collector HTTP client.

`PoliteHttpClient` is used by every site collector, but until now it was only
exercised indirectly through duck-typed fakes in the per-site suites. That
left the retry classification untested, and one gap in it ended a Saramin
backfill on 2026-09-09 — see `test_incomplete_read_is_retried`.

`urlopen` is patched in the module namespace rather than over the network, so
these run offline. `backoff_base_seconds=0` keeps them fast.
"""

from __future__ import annotations

from http.client import IncompleteRead
from typing import Self
from urllib.error import HTTPError, URLError

import pytest

from job.collector import http as http_module
from job.collector.http import BlockedError, HttpError, PoliteHttpClient


class _FakeResponse:
    """Minimal stand-in for the object `urlopen` yields."""

    def __init__(self, body: bytes | Exception) -> None:
        self._body = body

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def read(self) -> bytes:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _client(**overrides) -> PoliteHttpClient:
    values = {
        "base_url": "https://example.test",
        "backoff_base_seconds": 0.0,
        "backoff_cap_seconds": 0.0,
    }
    values.update(overrides)
    return PoliteHttpClient(**values)


def _patch_urlopen(monkeypatch, outcomes: list[bytes | Exception]):
    """Serve one outcome per attempt. Returns the call counter."""

    calls: list[str] = []

    def fake_urlopen(request, timeout=None):
        calls.append(request.full_url)
        outcome = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
        if isinstance(outcome, Exception) and not isinstance(outcome, IncompleteRead):
            raise outcome
        return _FakeResponse(outcome)

    monkeypatch.setattr(http_module, "urlopen", fake_urlopen)
    return calls


# --- the 2026-09-09 regression ----------------------------------------------


def test_incomplete_read_is_retried(monkeypatch):
    """A truncated chunked response must not end the run.

    `http.client.IncompleteRead` subclasses `HTTPException` only — not
    `OSError`, not `URLError` — so it used to propagate straight out of
    `get`. On 2026-09-09 that killed a Saramin backfill seven pages in
    ("IncompleteRead(29047 bytes read, 27065 more expected)") and every
    record collected up to that point was lost, because the collectors only
    write their batch after the crawl returns.
    """

    calls = _patch_urlopen(
        monkeypatch,
        [IncompleteRead(b"half", 27065), b"<html>full</html>"],
    )

    body = _client().get("/detail")

    assert body == "<html>full</html>"
    assert len(calls) == 2


def test_incomplete_read_on_every_attempt_raises_http_error(monkeypatch):
    """Exhausted retries surface as `HttpError`, which callers handle.

    The site collectors catch `HttpError` per posting and record a
    `detail_error`; an `IncompleteRead` reaching them uncaught does not.
    """

    calls = _patch_urlopen(monkeypatch, [IncompleteRead(b"half", 10)])

    with pytest.raises(HttpError, match="giving up after 3 attempts"):
        _client().get("/detail")

    assert len(calls) == 3


def test_incomplete_read_is_not_mistaken_for_a_block(monkeypatch):
    """A truncated read is transient, not a refusal.

    Classifying it as `BlockedError` would stop the whole site for the round.
    """

    _patch_urlopen(monkeypatch, [IncompleteRead(b"half", 10)])

    with pytest.raises(HttpError) as caught:
        _client().get("/detail")
    assert not isinstance(caught.value, BlockedError)


# --- the classifications it must not break ----------------------------------


def test_transport_errors_are_retried(monkeypatch):
    calls = _patch_urlopen(monkeypatch, [URLError("reset"), b"ok"])

    assert _client().get("/x") == "ok"
    assert len(calls) == 2


def test_refusal_status_raises_immediately(monkeypatch):
    """403 means retrying gets the IP banned, so it must not retry."""

    calls = _patch_urlopen(
        monkeypatch,
        [HTTPError("https://example.test/x", 403, "Forbidden", {}, None)],
    )

    with pytest.raises(BlockedError, match="refused with HTTP 403"):
        _client().get("/x")

    assert len(calls) == 1


def test_retryable_status_is_retried(monkeypatch):
    calls = _patch_urlopen(
        monkeypatch,
        [HTTPError("https://example.test/x", 503, "Unavailable", {}, None), b"ok"],
    )

    assert _client().get("/x") == "ok"
    assert len(calls) == 2


def test_non_retryable_status_raises_without_retry(monkeypatch):
    calls = _patch_urlopen(
        monkeypatch,
        [HTTPError("https://example.test/x", 404, "Not Found", {}, None)],
    )

    with pytest.raises(HttpError, match="HTTP 404"):
        _client().get("/x")

    assert len(calls) == 1


def test_block_page_under_a_200_is_detected(monkeypatch):
    _patch_urlopen(monkeypatch, ["<html>자동입력 방지".encode()])

    with pytest.raises(BlockedError, match="block page served"):
        _client().get("/x")


def test_non_http_url_never_reaches_urlopen(monkeypatch):
    calls = _patch_urlopen(monkeypatch, [b"ok"])

    with pytest.raises(HttpError, match="refusing non-http URL"):
        _client(base_url="file:///etc").get("passwd")

    assert calls == []
