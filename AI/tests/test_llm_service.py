import json
from pathlib import Path

import pytest

from llm.client import (
    OllamaError,
    OllamaSettings,
    build_chat_payload,
)
from llm.contracts import FactPack, TechnologySummary
from llm.service import (
    FIRST_TEMPERATURE,
    RETRY_TEMPERATURE,
    GeneratedSummary,
    SummaryStatus,
    generate_summary,
    parse_summary,
)

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
UNGROUNDED_SUMMARY = {**GROUNDED_SUMMARY, "summary": "WebSecurityAdapter 를 상속했다."}


def fact_pack(**overrides: object) -> FactPack:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload.update(overrides)
    return FactPack.model_validate(payload)


class FakeClient:
    """Answers with a queued reply per call and records the temperatures used."""

    model = "qwen3.5:4b"

    def __init__(self, *replies: object) -> None:
        self._replies = list(replies)
        self.temperatures: list[float] = []
        self.messages: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]], *, temperature: float) -> str:
        self.temperatures.append(temperature)
        self.messages.append(messages)
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return (
            reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        )


def generate(client: FakeClient, pack: FactPack | None = None) -> GeneratedSummary:
    return generate_summary(
        pack if pack is not None else fact_pack(),
        user_id="user-1",
        client=client,
    )


def test_accepted_summary_is_returned_after_one_call() -> None:
    client = FakeClient(GROUNDED_SUMMARY)

    result = generate(client)

    assert result.status is SummaryStatus.OK
    assert result.summary.headline == "인증 필터 체인을 직접 구성했다"
    assert client.temperatures == [FIRST_TEMPERATURE]


def test_rejected_summary_is_retried_at_temperature_zero() -> None:
    client = FakeClient(UNGROUNDED_SUMMARY, GROUNDED_SUMMARY)

    result = generate(client)

    assert result.status is SummaryStatus.OK
    assert client.temperatures == [FIRST_TEMPERATURE, RETRY_TEMPERATURE]
    assert result.attempts[0].failures[0].code == "UNGROUNDED_IDENTIFIER"


def test_two_rejections_fall_back_to_the_template() -> None:
    client = FakeClient(UNGROUNDED_SUMMARY, UNGROUNDED_SUMMARY)

    result = generate(client)

    assert result.status is SummaryStatus.FALLBACK
    assert result.summary.tech_id == "spring-security"
    assert len(client.temperatures) == 2


def test_the_model_is_never_asked_a_third_time() -> None:
    client = FakeClient(UNGROUNDED_SUMMARY, UNGROUNDED_SUMMARY)

    generate(client)

    assert len(client.messages) == 2


def test_an_unreachable_model_falls_back_instead_of_raising() -> None:
    client = FakeClient(OllamaError("connection refused"), OllamaError("still down"))

    result = generate(client)

    assert result.status is SummaryStatus.FALLBACK
    assert result.attempts[0].error == "connection refused"


def test_a_summary_for_the_wrong_technology_is_not_accepted() -> None:
    client = FakeClient(
        {**GROUNDED_SUMMARY, "tech_id": "spring-boot"}, GROUNDED_SUMMARY
    )

    result = generate(client)

    assert result.attempts[0].failures[0].code == "TECH_ID_MISMATCH"
    assert result.status is SummaryStatus.OK


def test_cache_key_is_reported_for_storage() -> None:
    result = generate(FakeClient(GROUNDED_SUMMARY))

    assert len(result.cache_key) == 64
    assert result.model == "qwen3.5:4b"
    assert result.prompt_version == "tech-summary/2026-09-15.1"


def test_fallback_keeps_the_same_cache_key_as_a_success() -> None:
    accepted = generate(FakeClient(GROUNDED_SUMMARY))
    fell_back = generate(FakeClient(UNGROUNDED_SUMMARY, UNGROUNDED_SUMMARY))

    assert accepted.cache_key == fell_back.cache_key


def test_parse_summary_reads_plain_json() -> None:
    content = json.dumps(GROUNDED_SUMMARY, ensure_ascii=False)

    assert parse_summary(content).tech_id == "spring-security"


def test_parse_summary_salvages_a_fenced_object() -> None:
    content = "```json\n" + json.dumps(GROUNDED_SUMMARY, ensure_ascii=False) + "\n```"

    assert isinstance(parse_summary(content), TechnologySummary)


def test_parse_summary_rejects_content_without_an_object() -> None:
    with pytest.raises(ValueError):
        parse_summary("요약을 만들 수 없습니다.")


def test_chat_payload_pins_the_bounded_options_and_the_response_schema() -> None:
    payload = build_chat_payload(
        [{"role": "user", "content": "x"}],
        settings=OllamaSettings(),
        temperature=FIRST_TEMPERATURE,
    )

    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["keep_alive"] == -1
    assert payload["options"] == {
        "num_ctx": 8_192,
        "num_predict": 300,
        "temperature": FIRST_TEMPERATURE,
    }
    assert payload["format"]["required"] == [
        "tech_id",
        "headline",
        "summary",
        "gap",
        "used_highlights",
        "confidence",
    ]


def test_settings_read_the_existing_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434/")
    monkeypatch.setenv("LLM_MODEL", "qwen3.5:8b")

    settings = OllamaSettings.from_env()

    assert settings.base_url == "http://host.docker.internal:11434"
    assert settings.model == "qwen3.5:8b"


def test_confidence_is_replaced_by_the_value_the_input_implies() -> None:
    overstated = {**GROUNDED_SUMMARY, "confidence": "LOW"}

    result = generate(FakeClient(overstated))

    assert result.status is SummaryStatus.OK
    assert result.summary.confidence.value == "HIGH"
    assert result.model_confidence is not None
    assert result.model_confidence.value == "LOW"


def test_an_agreeing_confidence_band_is_not_reported_as_drift() -> None:
    result = generate(FakeClient(GROUNDED_SUMMARY))

    assert result.model_confidence is None


def test_a_dependency_only_input_is_never_graded_high() -> None:
    pack = fact_pack(
        highlights=[
            {
                "index": 0,
                "fact_type": "DEPENDENCY",
                "value": "org.springframework.boot:spring-boot-starter-security",
                "file": "build.gradle",
                "mine": True,
            }
        ]
    )
    claimed_high = {
        **GROUNDED_SUMMARY,
        "summary": "build.gradle 에 spring-boot-starter-security 를 선언했다.",
    }

    result = generate(FakeClient(claimed_high), pack)

    assert result.summary.confidence.value == "MEDIUM"
