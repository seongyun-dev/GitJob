import json
from pathlib import Path

from fastapi.testclient import TestClient

from llm.client import OllamaError
from llm.server import create_app

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "llm"
    / "fixtures"
    / "technology_summary_request_v1.json"
)

GROUNDED_SUMMARY = {
    "tech_id": "spring-security",
    "headline": "인증 필터 체인을 직접 구성했다",
    "summary": "SecurityConfig 에서 SecurityFilterChain 을 정의했다.",
    "gap": "EnableMethodSecurity 를 켠 곳은 확인되지 않았다.",
    "used_highlights": [0],
    "confidence": "HIGH",
}


class FakeClient:
    model = "qwen3.5:4b"

    def __init__(self, *replies: object) -> None:
        self._replies = list(replies)
        self.prompts: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]], *, temperature: float) -> str:
        self.prompts.append(messages)
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return json.dumps(reply, ensure_ascii=False)


def request_payload(**overrides: object) -> dict[str, object]:
    payload = {
        "user_id": "user-1",
        "fact_pack": json.loads(FIXTURE_PATH.read_text(encoding="utf-8")),
    }
    payload.update(overrides)
    return payload


def test_health_reports_the_model_and_prompt_version() -> None:
    with TestClient(create_app(FakeClient())) as client:
        payload = client.get("/health").json()

    assert payload["status"] == "alive"
    assert payload["model"] == "qwen3.5:4b"
    assert payload["prompt_version"] == "tech-summary/2026-09-15.1"


def test_accepted_summary_is_returned_with_its_cache_key() -> None:
    with TestClient(create_app(FakeClient(GROUNDED_SUMMARY))) as client:
        response = client.post("/technology-summary", json=request_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["llm_status"] == "OK"
    assert body["summary"]["tech_id"] == "spring-security"
    assert len(body["cache_key"]) == 64


def test_a_down_model_answers_with_a_fallback_not_an_error() -> None:
    fake = FakeClient(OllamaError("connection refused"), OllamaError("still down"))

    with TestClient(create_app(fake)) as client:
        response = client.post("/technology-summary", json=request_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["llm_status"] == "FALLBACK"
    assert body["summary"]["summary"]
    assert body["attempts"][0]["error"] == "connection refused"


def test_rejected_generation_is_reported_by_failure_code() -> None:
    ungrounded = {**GROUNDED_SUMMARY, "summary": "WebSecurityAdapter 를 상속했다."}

    with TestClient(create_app(FakeClient(ungrounded, GROUNDED_SUMMARY))) as client:
        body = client.post("/technology-summary", json=request_payload()).json()

    assert body["llm_status"] == "OK"
    assert body["attempts"][0]["failure_codes"] == ["UNGROUNDED_IDENTIFIER"]


def test_invalid_fact_pack_is_rejected_before_any_generation() -> None:
    fake = FakeClient()
    payload = request_payload()
    payload["fact_pack"]["schema_version"] = "technology-summary-request/v2"

    with TestClient(create_app(fake)) as client:
        response = client.post("/technology-summary", json=payload)

    assert response.status_code == 422
    assert fake.prompts == []


def test_blank_user_id_is_rejected() -> None:
    with TestClient(create_app(FakeClient())) as client:
        response = client.post(
            "/technology-summary",
            json=request_payload(user_id="   "),
        )

    assert response.status_code == 422


def test_user_id_never_reaches_the_model() -> None:
    fake = FakeClient(GROUNDED_SUMMARY)

    with TestClient(create_app(fake)) as client:
        client.post(
            "/technology-summary",
            json=request_payload(user_id="octocat-9182"),
        )

    assert "octocat-9182" not in json.dumps(fake.prompts, ensure_ascii=False)
