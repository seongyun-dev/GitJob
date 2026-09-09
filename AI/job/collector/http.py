"""Polite HTTP client shared by the site collectors.

S15P21E102-101 fixes the behaviour: a per-site request interval, exponential
backoff with a fixed attempt ceiling, and a distinct error type for a refusal
so one blocked site can be stopped without stopping the others.

S15P21E102-159 and S15P21E102-148 each wrote their own copy of that. Adding a
third site is where it stops — nothing in this file was ever site-specific.
Worknet and JobKorea still carry their own clients; migrating them is a
follow-up kept out of this change so the open review stays readable.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

__all__ = [
    "BLOCK_MARKERS",
    "BlockedError",
    "HttpError",
    "PoliteHttpClient",
    "looks_blocked",
]

# "Slow down / try again", not "you are refused".
_RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
# The host refused this client outright. Retrying does not help and repeating
# the request against a refusal is exactly what gets an IP banned.
_REFUSAL_STATUSES = frozenset({401, 403, 406, 407, 451})

# Text that means "you are being blocked" even under a 200 response.
BLOCK_MARKERS: tuple[str, ...] = (
    "captcha",
    "자동입력 방지",
    "비정상적인 접근",
    "비정상적인 요청",
    "접근이 제한",
    "이용이 제한",
    "비정상적으로 많은",
    "too many requests",
    "access denied",
    "unusual traffic",
)


class HttpError(RuntimeError):
    """An HTTP or transport failure while collecting a page."""


class BlockedError(HttpError):
    """The host refused the request or served an access-block page.

    A separate type so a caller stops collecting this site and keeps the
    others running, instead of treating a ban as a transient error and
    hammering through the backoff ceiling.
    """


def looks_blocked(content: str) -> bool:
    """Detect a block page served with a success status."""

    lowered = content[:4000].lower()
    return any(marker.lower() in lowered for marker in BLOCK_MARKERS)


@dataclass(frozen=True)
class PoliteHttpClient:
    """GET pages with pacing, bounded retry and refusal detection.

    The client never decides on its own to keep hammering a refusing host:
    retries are capped, refusals raise immediately, and the caller supplies
    the interval.
    """

    base_url: str
    timeout: float = 30.0
    max_attempts: int = 3
    backoff_base_seconds: float = 0.8
    backoff_cap_seconds: float = 8.0
    # Identifies the collector rather than impersonating a browser, so the
    # site's operators can see who is asking and rate-limit us specifically.
    user_agent: str = "GitJob-JobCollector/0.1 (+SSAFY S15P21E102)"
    extra_headers: dict[str, str] = field(default_factory=dict)

    def absolute(self, url_or_path: str) -> str:
        return urljoin(self.base_url + "/", url_or_path)

    def get(
        self,
        url_or_path: str,
        params: Sequence[tuple[str, str]] | None = None,
        *,
        referer: str | None = None,
        delay_seconds: float = 0.0,
    ) -> str:
        url = self.absolute(url_or_path)
        if params:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode(params)}"
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        return self._request(url, referer=referer)

    def _request(self, url: str, *, referer: str | None) -> str:
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Language": "ko,en;q=0.8",
            **self.extra_headers,
        }
        if referer:
            headers["Referer"] = referer

        # Checked once, before any request: a base_url carrying file:// or
        # another scheme must not reach urlopen at all.
        if not url.lower().startswith(("http://", "https://")):
            raise HttpError(f"refusing non-http URL: {url}")

        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                with urlopen(
                    Request(url, headers=headers),
                    timeout=self.timeout,
                ) as response:
                    body = response.read().decode("utf-8", "replace")
            except HTTPError as error:
                if error.code in _REFUSAL_STATUSES:
                    raise BlockedError(
                        f"refused with HTTP {error.code} for {url}"
                    ) from error
                if error.code not in _RETRYABLE_STATUSES:
                    raise HttpError(f"HTTP {error.code} for {url}") from error
                last_error = error
            except (URLError, TimeoutError, OSError, HTTPException) as error:
                # `HTTPException` covers the ones that escape the three above,
                # and `http.client.IncompleteRead` is the one that matters: a
                # truncated chunked response. It subclasses `HTTPException`
                # only — not `OSError`, not `URLError` — so without it here a
                # half-delivered page propagates out of `get` and kills the
                # whole run. Observed 2026-09-09 on a Saramin detail page
                # ("IncompleteRead(29047 bytes read, 27065 more expected)"),
                # which ended a backfill seven pages in and lost every record
                # collected up to that point.
                last_error = error
            else:
                if looks_blocked(body):
                    raise BlockedError(f"block page served for {url}")
                return body

            if attempt < self.max_attempts:
                time.sleep(self._backoff_seconds(attempt))

        raise HttpError(
            f"giving up after {self.max_attempts} attempts for {url}: {last_error}"
        )

    def _backoff_seconds(self, attempt: int) -> float:
        return min(
            self.backoff_base_seconds * (2 ** (attempt - 1)), self.backoff_cap_seconds
        )
