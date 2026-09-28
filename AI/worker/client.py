"""Bounded delivery of A/B completion events to the internal C API."""

import json
import math
import time
from collections.abc import Callable, Mapping
from enum import StrEnum
from http.client import HTTPException
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    OpenerDirector,
    ProxyHandler,
    Request,
    build_opener,
)

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from worker.api import (
    AnalysisCompleted,
    Event,
    Identifier,
    JobCompleted,
    PublicReposCompleted,
    SnapshotId,
    TrendCompleted,
)

MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_RETRY_DELAY_SECONDS = 5.0


class CompletionKind(StrEnum):
    JOB_BATCH = "JOB_BATCH"
    ANALYSIS = "ANALYSIS"
    PUBLIC_REPO = "PUBLIC_REPO"
    TREND = "TREND"


_CONTRACTS = {
    CompletionKind.JOB_BATCH: (
        "/internal/v1/c/job-batches/completed",
        JobCompleted,
        frozenset({"COHORT", "DEMAND"}),
    ),
    CompletionKind.ANALYSIS: (
        "/internal/v1/c/analyses/completed",
        AnalysisCompleted,
        frozenset({"RECOMMENDATION"}),
    ),
    CompletionKind.PUBLIC_REPO: (
        "/internal/v1/c/public-repositories/completed",
        PublicReposCompleted,
        frozenset({"PUBLIC_GITHUB"}),
    ),
    CompletionKind.TREND: (
        "/internal/v1/c/trends/completed",
        TrendCompleted,
        frozenset({"TREND"}),
    ),
}
_RETRY_STATUSES = frozenset({202, 429, 500, 502, 503, 504})


class SubmissionError(RuntimeError):
    """Safe local error metadata; never retains response bodies or credentials."""

    def __init__(
        self,
        code: str,
        *,
        attempts: int,
        status_code: int | None = None,
        exhausted: bool = False,
    ):
        self.code = code
        self.attempts = attempts
        self.status_code = status_code
        self.exhausted = exhausted
        super().__init__(code)


class SnapshotReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["COHORT", "DEMAND", "RECOMMENDATION", "PUBLIC_GITHUB", "TREND"]
    snapshot_id: SnapshotId


class CompletionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: Identifier
    status: Literal["COMPLETED"]
    results: tuple[SnapshotReference, ...] = Field(min_length=1)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_submission(
    kind: CompletionKind | str, payload: Mapping[str, Any] | BaseModel
) -> tuple[CompletionKind, Event]:
    """Use the actual endpoint models without generating a new event identity."""
    try:
        selected = CompletionKind(kind)
        candidate = (
            payload.model_dump(mode="json")
            if isinstance(payload, BaseModel)
            else payload
        )
        event = _CONTRACTS[selected][1].model_validate(candidate)
    except (ValueError, TypeError):
        raise ValueError("INVALID_COMPLETION_INPUT") from None
    return selected, event


class CompletionClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_seconds: float = 10.0,
        max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        opener: OpenerDirector | None = None,
    ):
        try:
            parsed = urlsplit(base_url)
            _ = parsed.port
            valid_url = (
                parsed.scheme in {"http", "https"}
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and parsed.path in {"", "/"}
                and not parsed.query
                and not parsed.fragment
                and not any(character.isspace() for character in base_url)
            )
        except (ValueError, TypeError, AttributeError):
            valid_url = False
        if not valid_url:
            raise ValueError(
                "C_COMPUTE_URL must be an HTTP(S) origin without credentials or a path"
            )
        if (
            not isinstance(token, str)
            or not 32 <= len(token) <= 4096
            or any(not 33 <= ord(character) <= 126 for character in token)
        ):
            raise ValueError("Invalid C_COMPUTE_TOKEN")
        if (
            not isinstance(timeout_seconds, (float, int))
            or isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 60
        ):
            raise ValueError("timeout_seconds must be greater than zero and at most 60")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be an integer between 1 and 5")
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = float(timeout_seconds)
        self._max_attempts = max_attempts
        self._sleep = sleep
        # Internal service credentials must not be sent through ambient proxies.
        self._opener = (
            opener
            if opener is not None
            else build_opener(ProxyHandler({}), _NoRedirect())
        )

    def submit(
        self, kind: CompletionKind | str, payload: Mapping[str, Any] | BaseModel
    ) -> CompletionReceipt:
        selected, event = validate_submission(kind, payload)
        path, _, expected_kinds = _CONTRACTS[selected]
        try:
            body = json.dumps(
                event.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (ValueError, TypeError):
            raise ValueError("INVALID_COMPLETION_INPUT") from None
        if len(body) > MAX_REQUEST_BYTES:
            raise ValueError("COMPLETION_INPUT_TOO_LARGE")
        for attempt in range(1, self._max_attempts + 1):
            request = Request(
                self._base_url + path,
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            # Defense in depth even if an embedding application changes handlers.
            request.add_unredirected_header("Authorization", f"Bearer {self._token}")
            status, headers, response_body = None, {}, b""
            try:
                try:
                    response = self._opener.open(request, timeout=self._timeout)
                except HTTPError as error:
                    response = error
                with response:
                    status = response.getcode()
                    headers = response.headers
                    response_body = response.read(MAX_RESPONSE_BYTES + 1)
            except (TimeoutError, URLError):
                # A timeout can occur after 200 headers but before the complete
                # receipt. Its completion is still uncertain, so retry the event.
                status, headers, response_body = None, {}, b""
            except (OSError, HTTPException):
                raise SubmissionError("TRANSPORT_FAILED", attempts=attempt) from None
            if len(response_body) > MAX_RESPONSE_BYTES:
                raise SubmissionError(
                    "RESPONSE_TOO_LARGE", attempts=attempt, status_code=status
                )
            if status == 200:
                return self._receipt(
                    response_body, event.event_id, expected_kinds, attempt
                )
            error_code = self._response_error_code(response_body)
            retry = (
                status is None
                or status in _RETRY_STATUSES
                or (status == 409 and error_code == "LEASE_LOST")
            )
            if not retry:
                code = (
                    "IDEMPOTENCY_CONFLICT"
                    if status == 409 and error_code == "IDEMPOTENCY_CONFLICT"
                    else f"HTTP_{status}"
                )
                raise SubmissionError(
                    code, attempts=attempt, status_code=status
                ) from None
            if attempt == self._max_attempts:
                raise SubmissionError(
                    "RETRY_EXHAUSTED",
                    attempts=attempt,
                    status_code=status,
                    exhausted=True,
                ) from None
            self._sleep(self._retry_delay(headers, attempt))
        raise AssertionError("bounded attempts must complete or raise")

    @staticmethod
    def _response_error_code(body: bytes) -> str | None:
        try:
            value = json.loads(body)
        except (ValueError, UnicodeError):
            return None
        code = value.get("code") if isinstance(value, dict) else None
        # Never propagate an arbitrary server message or code into logs/errors.
        return code if code in ("LEASE_LOST", "IDEMPOTENCY_CONFLICT") else None

    @staticmethod
    def _retry_delay(headers, attempt: int) -> float:
        default = min(0.5 * 2 ** (attempt - 1), MAX_RETRY_DELAY_SECONDS)
        try:
            requested = float(headers.get("Retry-After", default))
        except (ValueError, TypeError):
            return default
        if not math.isfinite(requested):
            return default
        return min(max(requested, 0.0), MAX_RETRY_DELAY_SECONDS)

    @staticmethod
    def _receipt(
        body: bytes, event_id: str, expected_kinds: frozenset[str], attempt: int
    ) -> CompletionReceipt:
        try:
            response = json.loads(body)
            receipt = CompletionReceipt.model_validate(response["data"])
            if (
                receipt.event_id != event_id
                or {reference.kind for reference in receipt.results} != expected_kinds
                or len(receipt.results) != len(expected_kinds)
                or len({reference.snapshot_id for reference in receipt.results})
                != len(receipt.results)
            ):
                raise ValueError("unexpected completion references")
        except (ValueError, TypeError, KeyError, UnicodeError, ValidationError):
            raise SubmissionError(
                "INVALID_RESPONSE", attempts=attempt, status_code=200
            ) from None
        return receipt
