"""Polite standard-library HTTP client for JobKorea's public pages."""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


class JobKoreaHttpError(RuntimeError):
    """An HTTP or transport failure while collecting a page."""


class JobKoreaBlockedError(JobKoreaHttpError):
    """The site refused the request or returned an access-block page."""


@dataclass(frozen=True)
class JobKoreaHttpClient:
    base_url: str = "https://www.jobkorea.co.kr"
    timeout: float = 30.0
    max_attempts: int = 3
    user_agent: str = "GitJob-JobKoreaCrawler/0.1"

    def get(
        self,
        url_or_path: str,
        *,
        referer: str | None = None,
        delay_seconds: float = 0.0,
    ) -> str:
        return self._request_text(
            "GET",
            url_or_path,
            referer=referer,
            delay_seconds=delay_seconds,
        )

    def get_bytes(
        self,
        url_or_path: str,
        *,
        referer: str | None = None,
        delay_seconds: float = 0.0,
    ) -> bytes:
        """Fetch a public asset without decoding it as page text."""

        return self._request_bytes(
            "GET",
            url_or_path,
            referer=referer,
            delay_seconds=delay_seconds,
        )

    def post(
        self,
        url_or_path: str,
        data: Sequence[tuple[str, str]],
        *,
        referer: str | None = None,
        delay_seconds: float = 0.0,
    ) -> str:
        encoded = urlencode(list(data)).encode("utf-8")
        return self._request_text(
            "POST",
            url_or_path,
            data=encoded,
            referer=referer,
            delay_seconds=delay_seconds,
        )

    def _request_text(
        self,
        method: str,
        url_or_path: str,
        *,
        data: bytes | None = None,
        referer: str | None,
        delay_seconds: float,
    ) -> str:
        content, charset = self._request(
            method,
            url_or_path,
            data=data,
            referer=referer,
            delay_seconds=delay_seconds,
        )
        return content.decode(charset, errors="replace")

    def _request_bytes(
        self,
        method: str,
        url_or_path: str,
        *,
        data: bytes | None = None,
        referer: str | None,
        delay_seconds: float,
    ) -> bytes:
        content, _ = self._request(
            method,
            url_or_path,
            data=data,
            referer=referer,
            delay_seconds=delay_seconds,
        )
        return content

    def _request(
        self,
        method: str,
        url_or_path: str,
        *,
        data: bytes | None = None,
        referer: str | None,
        delay_seconds: float,
    ) -> tuple[bytes, str]:
        url = urljoin(self.base_url.rstrip("/") + "/", url_or_path)
        if delay_seconds > 0:
            time.sleep(delay_seconds)

        headers = {
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
            "User-Agent": self.user_agent,
        }
        if referer:
            headers["Referer"] = referer
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
            headers["X-Requested-With"] = "XMLHttpRequest"

        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            request = Request(url, data=data, headers=headers, method=method)
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    charset = response.headers.get_content_charset() or "utf-8"
                    content = response.read()
                    if _looks_blocked(content.decode(charset, errors="replace")):
                        raise JobKoreaBlockedError(
                            "JobKorea returned an access-block or CAPTCHA page"
                        )
                    return content, charset
            except HTTPError as error:
                last_error = error
                retryable = error.code == 429 or 500 <= error.code <= 599
                if not retryable:
                    if error.code in {401, 403, 406, 407, 451}:
                        raise JobKoreaBlockedError(
                            f"JobKorea refused {method} {url} with HTTP {error.code}"
                        ) from error
                    raise JobKoreaHttpError(
                        f"JobKorea returned HTTP {error.code} for {method} {url}"
                    ) from error
            except (URLError, TimeoutError, OSError, HTTPException) as error:
                # Same widening as `Worknet_Collector_V1.client` and the shared
                # `PoliteHttpClient` — see that client's comment for why
                # `URLError` alone lets `IncompleteRead`, `TimeoutError` and a
                # plain `OSError` escape `read()` and end the whole round
                # (S15P21E102-173).
                #
                # Fixed here even though S15P21E102-94 §1 concluded this
                # collector should be discarded: it is still in the tree, still
                # importable, and leaving a known defect in code that exists is
                # worse than a few lines that will be deleted with it.
                #
                # The discard is S15P21E102-195, which has to land after this
                # commit — it deletes the file this hunk edits.
                last_error = error

            if attempt + 1 < self.max_attempts:
                time.sleep(min(8.0, 0.8 * (2**attempt)))

        raise JobKoreaHttpError(
            "JobKorea request failed after "
            f"{self.max_attempts} attempts: {method} {url}"
        ) from last_error


def _looks_blocked(content: str) -> bool:
    lowered = content.lower()
    markers = (
        "captcha",
        "자동입력 방지",
        "비정상적인 접근",
        "접근이 제한",
        "too many requests",
    )
    return any(marker in lowered for marker in markers)
