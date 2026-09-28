"""Reusable GitHub HTTP boundary for repository collection jobs.

The client keeps credentials only in request memory, never sends them to the
raw content host, and returns response metadata instead of hiding failures.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from http.client import IncompleteRead
from typing import Any, Protocol

API_ROOT = "https://api.github.com"
RAW_ROOT = "https://raw.githubusercontent.com"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class RateLimitState:
    limit: int | None
    remaining: int | None
    used: int | None
    reset: int | None
    resource: str | None

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> RateLimitState:
        lowered = {key.lower(): value for key, value in headers.items()}
        return cls(
            limit=_optional_int(lowered.get("x-ratelimit-limit")),
            remaining=_optional_int(lowered.get("x-ratelimit-remaining")),
            used=_optional_int(lowered.get("x-ratelimit-used")),
            reset=_optional_int(lowered.get("x-ratelimit-reset")),
            resource=lowered.get("x-ratelimit-resource"),
        )


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class HttpTransport(Protocol):
    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse: ...


class UrllibTransport:
    """stdlib transport that returns HTTP error responses without logging headers."""

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        request = urllib.request.Request(url, headers=dict(headers))
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResponse(
                    status=int(response.status),
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except urllib.error.HTTPError as exc:
            return HttpResponse(
                status=int(exc.code),
                headers=dict(exc.headers.items()) if exc.headers else {},
                body=exc.read(),
            )


@dataclass(frozen=True)
class RequestRecord:
    stage: str
    endpoint_category: str
    http_status: int
    response_bytes: int
    elapsed_seconds: float
    is_core: bool
    rate_limit_limit: int | None = None
    rate_limit_remaining: int | None = None
    rate_limit_used: int | None = None
    rate_limit_reset: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class RequestOutcome:
    response: HttpResponse | None
    records: tuple[RequestRecord, ...]
    payload: Mapping[str, Any] | None


class GitHubClient:
    """Small GitHub REST/raw client with bounded retry and safe auth routing."""

    def __init__(
        self,
        token: str,
        *,
        transport: HttpTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        user_agent: str = "GitJob-Repo-Fetch/1.0",
    ) -> None:
        if not token:
            raise ValueError("a GitHub token is required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds cannot be negative")
        if not user_agent.strip():
            raise ValueError("user_agent must not be blank")
        self._token = token
        self.transport = transport or UrllibTransport()
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.sleep = sleep
        self.user_agent = user_agent

    def core_rate_limit(self) -> tuple[RateLimitState, tuple[RequestRecord, ...]]:
        outcome = self._request(
            f"{API_ROOT}/rate_limit",
            stage="CONTROL",
            endpoint_category="rest_core_rate_limit",
            is_core=True,
        )
        payload = outcome.payload or {}
        core = payload.get("resources", {}).get("core", {})
        if isinstance(core, Mapping):
            state = RateLimitState(
                limit=_optional_int(core.get("limit")),
                remaining=_optional_int(core.get("remaining")),
                used=_optional_int(core.get("used")),
                reset=_optional_int(core.get("reset")),
                resource="core",
            )
        elif outcome.response is not None:
            state = RateLimitState.from_headers(outcome.response.headers)
        else:
            state = RateLimitState(None, None, None, None, None)
        return state, outcome.records

    def get_json(
        self,
        path: str,
        *,
        stage: str | Enum,
        endpoint_category: str,
    ) -> RequestOutcome:
        return self._request(
            f"{API_ROOT}{path}",
            stage=_stage_value(stage),
            endpoint_category=endpoint_category,
            is_core=True,
        )

    def get_raw(
        self,
        url: str,
        *,
        stage: str | Enum = "D_MANIFEST",
        endpoint_category: str = "manifest_raw",
        prefix_bytes: int | None = None,
    ) -> RequestOutcome:
        if not url.startswith(f"{RAW_ROOT}/"):
            raise ValueError("raw URL must use raw.githubusercontent.com")
        if prefix_bytes is not None and prefix_bytes < 1:
            raise ValueError("prefix_bytes must be positive")
        headers = (
            {"Range": f"bytes=0-{prefix_bytes - 1}"}
            if prefix_bytes is not None
            else None
        )
        return self._request(
            url,
            stage=_stage_value(stage),
            endpoint_category=endpoint_category,
            is_core=False,
            expect_json=False,
            extra_headers=headers,
            response_prefix_bytes=prefix_bytes,
        )

    def _request(
        self,
        url: str,
        *,
        stage: str,
        endpoint_category: str,
        is_core: bool,
        expect_json: bool = True,
        extra_headers: Mapping[str, str] | None = None,
        response_prefix_bytes: int | None = None,
    ) -> RequestOutcome:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": self.user_agent,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if extra_headers:
            headers.update(extra_headers)
        if is_core:
            headers["Authorization"] = f"Bearer {self._token}"

        records: list[RequestRecord] = []
        response: HttpResponse | None = None
        for attempt in range(self.max_attempts):
            started = time.perf_counter()
            try:
                response = self.transport.request(
                    url,
                    headers=headers,
                    timeout=self.timeout,
                )
            except (IncompleteRead, OSError, TimeoutError) as exc:
                records.append(
                    RequestRecord(
                        stage=stage,
                        endpoint_category=endpoint_category,
                        http_status=0,
                        response_bytes=0,
                        elapsed_seconds=time.perf_counter() - started,
                        is_core=is_core,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                if attempt + 1 >= self.max_attempts:
                    break
                self.sleep(self.backoff_seconds * (2**attempt))
                continue

            received_bytes = len(response.body)
            if response_prefix_bytes is not None:
                response = HttpResponse(
                    status=response.status,
                    headers=response.headers,
                    body=response.body[:response_prefix_bytes],
                )
            rate = RateLimitState.from_headers(response.headers)
            records.append(
                RequestRecord(
                    stage=stage,
                    endpoint_category=endpoint_category,
                    http_status=response.status,
                    response_bytes=received_bytes,
                    elapsed_seconds=time.perf_counter() - started,
                    is_core=is_core,
                    rate_limit_limit=rate.limit,
                    rate_limit_remaining=rate.remaining,
                    rate_limit_used=rate.used,
                    rate_limit_reset=rate.reset,
                )
            )
            if response.status < 500 or attempt + 1 >= self.max_attempts:
                break
            self.sleep(self.backoff_seconds * (2**attempt))

        payload: Mapping[str, Any] | None = None
        if response is not None and expect_json and response.body:
            try:
                decoded = json.loads(response.body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                decoded = None
            if isinstance(decoded, Mapping):
                payload = decoded
        return RequestOutcome(
            response=response,
            records=tuple(records),
            payload=payload,
        )


def _stage_value(stage: str | Enum) -> str:
    return str(stage.value) if isinstance(stage, Enum) else str(stage)


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
