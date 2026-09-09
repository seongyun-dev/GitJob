"""Polite standard-library HTTP client for Worknet's public pages.

Request pacing, bounded retry and block detection live here so the crawler
never decides on its own to keep hammering a refusing host. This mirrors the
S15P21E102-101 contract: per-site interval, exponential backoff with a fixed
attempt ceiling, and a distinct error type for refusals so one blocked site
can be stopped without stopping the others.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://www.work24.go.kr"

# Statuses that mean "slow down / try again", not "you are refused".
_RETRYABLE_STATUSES = frozenset({408, 425, 429})
# Statuses that mean the host refused this client outright.
_REFUSAL_STATUSES = frozenset({401, 403, 406, 407, 451})

_BLOCK_MARKERS = (
    "captcha",
    "자동입력 방지",
    "비정상적인 접근",
    "비정상적인 요청",
    "접근이 제한",
    "이용이 제한",
    "too many requests",
    "access denied",
)


class WorknetHttpError(RuntimeError):
    """An HTTP or transport failure while collecting a page."""


class WorknetBlockedError(WorknetHttpError):
    """Worknet refused the request or returned an access-block page.

    Callers stop collecting this site and keep other sites running.
    """


@dataclass(frozen=True)
class WorknetHttpClient:
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 30.0
    max_attempts: int = 3
    backoff_base_seconds: float = 0.8
    backoff_cap_seconds: float = 8.0
    user_agent: str = "GitJob-WorknetCollector/0.1"

    def get(
        self,
        url_or_path: str,
        params: Sequence[tuple[str, str]] | None = None,
        *,
        referer: str | None = None,
        delay_seconds: float = 0.0,
    ) -> str:
        target = url_or_path
        if params:
            separator = "&" if "?" in target else "?"
            target = f"{target}{separator}{urlencode(list(params))}"
        return self._request(target, referer=referer, delay_seconds=delay_seconds)

    def absolute(self, url_or_path: str) -> str:
        return urljoin(self.base_url.rstrip("/") + "/", url_or_path)

    def _request(
        self,
        url_or_path: str,
        *,
        referer: str | None,
        delay_seconds: float,
    ) -> str:
        url = self.absolute(url_or_path)
        if delay_seconds > 0:
            time.sleep(delay_seconds)

        headers = {
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
            "User-Agent": self.user_agent,
        }
        if referer:
            headers["Referer"] = referer

        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            request = Request(url, headers=headers, method="GET")
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    charset = response.headers.get_content_charset() or "utf-8"
                    body = response.read().decode(charset, errors="replace")
                    if looks_blocked(body):
                        raise WorknetBlockedError(
                            f"Worknet returned an access-block page for {url}"
                        )
                    return body
            except HTTPError as error:
                last_error = error
                if error.code in _REFUSAL_STATUSES:
                    raise WorknetBlockedError(
                        f"Worknet refused GET {url} with HTTP {error.code}"
                    ) from error
                retryable = error.code in _RETRYABLE_STATUSES or 500 <= error.code < 600
                if not retryable:
                    raise WorknetHttpError(
                        f"Worknet returned HTTP {error.code} for GET {url}"
                    ) from error
            except (URLError, TimeoutError, OSError, HTTPException) as error:
                # `URLError` alone was not enough. `response.read()` above can
                # raise three things it does not cover:
                #
                #   http.client.IncompleteRead   a truncated chunked response.
                #                                Subclasses `HTTPException`
                #                                only — not `OSError`, not
                #                                `URLError`
                #   TimeoutError                 socket timeout during read.
                #                                An `OSError`, but not a
                #                                `URLError`
                #   plain OSError                connection reset
                #
                # `URLError` subclasses `OSError`, but not the other way
                # round, so `except URLError` let all three propagate out of
                # `get` and end the whole round. That is S15P21E102-173, which
                # killed a Saramin backfill seven pages in; this client is the
                # same defect in the collector that gathers the most postings
                # (5,648 across 15 rounds).
                #
                # Worknet's own exceptions are `RuntimeError` subclasses, so
                # the block page raised inside the `try` above is not caught
                # here.
                last_error = error

            if attempt + 1 < self.max_attempts:
                time.sleep(self._backoff_seconds(attempt))

        raise WorknetHttpError(
            f"Worknet request failed after {self.max_attempts} attempts: GET {url}"
        ) from last_error

    def _backoff_seconds(self, attempt: int) -> float:
        return min(self.backoff_cap_seconds, self.backoff_base_seconds * (2**attempt))


def looks_blocked(content: str) -> bool:
    """True when a 200 response body is actually a block or CAPTCHA page."""

    lowered = content.lower()
    return any(marker in lowered for marker in _BLOCK_MARKERS)
