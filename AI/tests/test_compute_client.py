import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError, URLError

import pytest
from test_job_cohort import batch, criteria, posting
from test_recommendation_engine import make_analysis

from worker.client import CompletionClient, SubmissionError

TOKEN = "local-client-test-token-only-00000000"


def job_event():
    return {
        "schema_version": "c-compute-event/v1",
        "event_id": "event-1",
        "trace_id": "trace-1",
        "occurred_at": "2026-09-08T00:00:00Z",
        "batch": batch(posting()).model_dump(mode="json"),
        "criteria": criteria().model_dump(mode="json"),
    }


def completed(*, event_id="event-1", kind="JOB_BATCH"):
    kinds = {
        "JOB_BATCH": ("COHORT", "DEMAND"),
        "ANALYSIS": ("RECOMMENDATION",),
        "PUBLIC_REPO": ("PUBLIC_GITHUB",),
        "TREND": ("TREND",),
    }[kind]
    return {
        "message": "complete",
        "data": {
            "event_id": event_id,
            "status": "COMPLETED",
            "results": [
                {"kind": item, "snapshot_id": "c-" + str(index) * 64}
                for index, item in enumerate(kinds, start=1)
            ],
        },
    }


class Response(io.BytesIO):
    def __init__(self, payload, *, status=200, headers=None):
        super().__init__(
            payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        )
        self.status = status
        self.headers = headers or {}

    def getcode(self):
        return self.status


class Opener:
    def __init__(self, *effects):
        self.effects = list(effects)
        self.calls = []

    def open(self, request, *, timeout):
        self.calls.append((request, timeout))
        effect = self.effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


def failure(status, code="UNSAFE secret-token-body", headers=None):
    return HTTPError(
        "http://internal.invalid",
        status,
        "unsafe reason",
        headers or {},
        io.BytesIO(json.dumps({"code": code, "message": TOKEN}).encode()),
    )


def test_retries_reuse_identical_event_bytes_trace_and_token_with_bounded_delay():
    delays = []
    opener = Opener(
        Response({}, status=202, headers={"Retry-After": "9999"}),
        failure(409, "LEASE_LOST"),
        Response(completed()),
    )
    client = CompletionClient(
        "http://worker:8000", TOKEN, opener=opener, sleep=delays.append
    )
    receipt = client.submit("JOB_BATCH", job_event())
    assert receipt.status == "COMPLETED"
    assert {item.kind for item in receipt.results} == {"COHORT", "DEMAND"}
    assert len(opener.calls) == 3
    assert len({request.data for request, _ in opener.calls}) == 1
    assert all(
        request.get_header("Authorization") == f"Bearer {TOKEN}"
        for request, _ in opener.calls
    )
    assert all(
        request.full_url == "http://worker:8000/internal/v1/c/job-batches/completed"
        for request, _ in opener.calls
    )
    assert all(0 < timeout <= 60 for _, timeout in opener.calls)
    assert all(0 <= delay <= 5 for delay in delays)
    assert json.loads(opener.calls[0][0].data)["trace_id"] == "trace-1"


@pytest.mark.parametrize(
    "effect",
    [
        TimeoutError("secret"),
        URLError("secret"),
        *[failure(code) for code in (429, 500, 502, 503, 504)],
    ],
)
def test_only_transient_conditions_retry_to_completion(effect):
    opener = Opener(effect, Response(completed()))
    assert (
        CompletionClient("http://worker", TOKEN, opener=opener, sleep=lambda _: None)
        .submit("JOB_BATCH", job_event())
        .status
        == "COMPLETED"
    )
    assert len(opener.calls) == 2


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "BAD"),
        (401, "BAD"),
        (403, "BAD"),
        (404, "BAD"),
        (409, "IDEMPOTENCY_CONFLICT"),
        (409, "OTHER"),
        (422, "BAD"),
        (301, "REDIRECT"),
        (302, "REDIRECT"),
        (307, "REDIRECT"),
        (501, "BAD"),
    ],
)
def test_permanent_errors_never_retry_or_expose_response_body(status, code):
    opener = Opener(failure(status, code))
    with pytest.raises(SubmissionError) as caught:
        CompletionClient("http://worker", TOKEN, opener=opener).submit(
            "JOB_BATCH", job_event()
        )
    assert len(opener.calls) == 1
    assert not caught.value.exhausted
    assert TOKEN not in str(caught.value)
    assert "unsafe" not in str(caught.value)


def test_exhausted_preparing_is_not_reported_as_completed():
    opener = Opener(Response({}, status=202), Response({}, status=202))
    with pytest.raises(SubmissionError) as caught:
        CompletionClient(
            "http://worker", TOKEN, max_attempts=2, opener=opener, sleep=lambda _: None
        ).submit("JOB_BATCH", job_event())
    assert caught.value.exhausted
    assert caught.value.attempts == 2
    assert caught.value.code == "RETRY_EXHAUSTED"


def test_timeout_while_reading_200_body_still_retries_identical_event():
    class SlowBody(Response):
        def read(self, size=-1):
            raise TimeoutError("secret from upstream")

    opener = Opener(SlowBody(b"", status=200), Response(completed()))
    receipt = CompletionClient(
        "http://worker", TOKEN, opener=opener, sleep=lambda _: None
    ).submit("JOB_BATCH", job_event())
    assert receipt.status == "COMPLETED"
    assert len(opener.calls) == 2
    assert opener.calls[0][0].data == opener.calls[1][0].data


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        completed(event_id="different-event"),
        {"data": {"event_id": "event-1", "status": "PREPARING", "results": []}},
        completed(kind="TREND"),
    ],
)
def test_200_requires_matching_completed_event_and_expected_result_references(payload):
    opener = Opener(Response(payload))
    with pytest.raises(SubmissionError, match="INVALID_RESPONSE"):
        CompletionClient("http://worker", TOKEN, opener=opener).submit(
            "JOB_BATCH", job_event()
        )
    assert len(opener.calls) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"base_url": "https://name:password@example.com"},
        {"base_url": "https://example.com/path"},
        {"base_url": "https://example.com?token=x"},
        {"token": "x\r\nAuthorization: stolen"},
        {"timeout_seconds": 0},
        {"timeout_seconds": 61},
        {"max_attempts": 0},
        {"max_attempts": 6},
    ],
)
def test_configuration_is_bounded_and_credential_bearing_urls_are_rejected(kwargs):
    with pytest.raises(ValueError):
        CompletionClient(**{"base_url": "http://worker", "token": TOKEN, **kwargs})


def test_unknown_kind_and_invalid_input_do_not_make_requests():
    opener = Opener()
    client = CompletionClient("http://worker", TOKEN, opener=opener)
    for kind, payload in (
        ("../../other", job_event()),
        ("JOB_BATCH", {"event_id": "bad"}),
    ):
        with pytest.raises(ValueError):
            client.submit(kind, payload)
    assert not opener.calls


@pytest.mark.parametrize(
    "kind,path",
    [
        ("ANALYSIS", "/analyses/completed"),
        ("PUBLIC_REPO", "/public-repositories/completed"),
        ("TREND", "/trends/completed"),
    ],
)
def test_other_completion_kinds_use_actual_api_models_and_only_allowlisted_paths(
    kind, path
):
    payload = {
        key: value
        for key, value in job_event().items()
        if key not in {"batch", "criteria"}
    }
    if kind == "ANALYSIS":
        evidence = make_analysis()
        payload.update(
            user_id=evidence.user_id,
            analysis_id=evidence.analysis_id,
            cohort_snapshot_id="c-" + "a" * 64,
            evidence=evidence.model_dump(mode="json"),
        )
    elif kind == "PUBLIC_REPO":
        payload["batch"] = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "github/fixtures/github_repo_snapshot_v1.json"
            ).read_text(encoding="utf-8")
        )
    else:
        payload.update(tech_id="python", source="GITHUB", periods=["2026-Q2"])
    opener = Opener(Response(completed(kind=kind)))
    receipt = CompletionClient("https://worker", TOKEN, opener=opener).submit(
        kind, payload
    )
    assert receipt.status == "COMPLETED"
    assert opener.calls[0][0].full_url == "https://worker/internal/v1/c" + path


def test_oversized_response_is_bounded_and_never_echoed():
    opener = Opener(Response(b"x" * (1024 * 1024 + 1)))
    with pytest.raises(SubmissionError, match="RESPONSE_TOO_LARGE"):
        CompletionClient("http://worker", TOKEN, opener=opener).submit(
            "JOB_BATCH", job_event()
        )
    assert len(opener.calls) == 1


def test_real_urllib_does_not_follow_redirect_or_forward_authorization():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append((self.path, self.headers.get("Authorization")))
            self.send_response(307)
            self.send_header("Location", "/must-not-receive-token")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(SubmissionError):
            CompletionClient(f"http://127.0.0.1:{server.server_port}", TOKEN).submit(
                "JOB_BATCH", job_event()
            )
        assert seen == [("/internal/v1/c/job-batches/completed", f"Bearer {TOKEN}")]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
