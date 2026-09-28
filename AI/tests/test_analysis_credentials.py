from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from analysis.clone import PermanentCloneError, TransientCloneError
from analysis.credentials import HttpCredentialBroker

CONTRACT_ROOT = Path(__file__).resolve().parents[2] / "docs" / "data" / "contracts"


def request(broker: HttpCredentialBroker) -> str:
    return broker.access_token_for(
        analysis_id="an_1",
        analysis_repository_id="ar_1",
        github_repository_id=123,
        repository_full_name="octocat/private",
        commit_sha="a" * 40,
    )


def test_broker_sends_exact_tuple_and_service_token(monkeypatch):
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(
                {
                    "message": "ok",
                    "data": {
                        "schema_version": "repository-analysis-credential-response/v1",
                        "credential_type": "GITHUB_OAUTH_ACCESS_TOKEN",
                        "access_token": "github-token",
                    },
                }
            ).encode()

    def urlopen(http_request, timeout):
        captured["request"] = http_request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("analysis.credentials.urlopen", urlopen)
    broker = HttpCredentialBroker(
        "http://backend:8080/internal/v1/repository-analysis/credentials",
        "worker-token",
        timeout_seconds=3,
    )

    assert request(broker) == "github-token"
    assert captured["request"].get_header("Authorization") == "Bearer worker-token"
    request_body = json.loads(captured["request"].data)
    assert request_body == {
        "schema_version": "repository-analysis-credential-request/v1",
        "analysis_id": "an_1",
        "analysis_repository_id": "ar_1",
        "github_repository_id": 123,
        "repository_full_name": "octocat/private",
        "commit_sha": "a" * 40,
    }
    request_schema = json.loads(
        (CONTRACT_ROOT / "repository-analysis-credential-request-v1.schema.json")
        .read_text(encoding="utf-8")
    )
    Draft202012Validator(request_schema).validate(request_body)


def test_response_contract_accepts_the_backend_envelope():
    response_schema = json.loads(
        (CONTRACT_ROOT / "repository-analysis-credential-response-v1.schema.json")
        .read_text(encoding="utf-8")
    )

    Draft202012Validator(response_schema).validate(
        {
            "message": "저장소 분석 자격증명을 발급했습니다.",
            "data": {
                "schema_version": "repository-analysis-credential-response/v1",
                "credential_type": "GITHUB_OAUTH_ACCESS_TOKEN",
                "access_token": "fixture-token",
            },
        }
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        "",
        "file:///tmp/credential.json",
        "ftp://backend/internal",
        "https://worker:secret@backend/internal",
        "https://backend/internal#credential",
    ],
)
def test_broker_rejects_unsafe_or_non_http_endpoints(endpoint):
    with pytest.raises(ValueError, match=r"HTTP\(S\) URL"):
        HttpCredentialBroker(endpoint, "service-token")


@pytest.mark.parametrize(
    "data",
    [
        {
            "schema_version": "repository-analysis-credential-response/v0",
            "credential_type": "GITHUB_OAUTH_ACCESS_TOKEN",
            "access_token": "github-token",
        },
        {
            "schema_version": "repository-analysis-credential-response/v1",
            "credential_type": "UNKNOWN",
            "access_token": "github-token",
        },
    ],
)
def test_broker_rejects_an_unexpected_response_contract(monkeypatch, data):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps({"message": "ok", "data": data}).encode()

    monkeypatch.setattr(
        "analysis.credentials.urlopen", lambda *_args, **_kwargs: Response()
    )

    with pytest.raises(TransientCloneError) as failure:
        request(HttpCredentialBroker("http://backend/internal", "service-token"))

    assert failure.value.code == "CREDENTIAL_BROKER_INVALID_RESPONSE"


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_broker_statuses_are_retried(monkeypatch, status):
    def unavailable(*_args, **_kwargs):
        raise urllib.error.HTTPError("url", status, "error", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr("analysis.credentials.urlopen", unavailable)

    with pytest.raises(TransientCloneError) as failure:
        request(HttpCredentialBroker("http://backend/internal", "service-token"))

    assert failure.value.code == "CREDENTIAL_BROKER_UNAVAILABLE"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "CREDENTIAL_BROKER_UNAUTHORIZED"),
        (404, "REPOSITORY_CREDENTIAL_NOT_FOUND"),
        (409, "ANALYSIS_NOT_ACTIVE"),
        (424, "GITHUB_RECONNECT_REQUIRED"),
    ],
)
def test_terminal_broker_statuses_have_stable_worker_codes(monkeypatch, status, code):
    def rejected(*_args, **_kwargs):
        raise urllib.error.HTTPError("url", status, "error", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr("analysis.credentials.urlopen", rejected)

    with pytest.raises(PermanentCloneError) as failure:
        request(HttpCredentialBroker("http://backend/internal", "service-token"))

    assert failure.value.code == code
