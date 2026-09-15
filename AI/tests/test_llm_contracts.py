import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from llm.contracts import (
    Authorship,
    Confidence,
    EvidenceLevel,
    FactPack,
    TechnologySummary,
    shorten_file_path,
    technology_summary_json_schema,
)

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "data"
    / "contracts"
    / "technology-summary-v1.schema.json"
)
FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "llm"
    / "fixtures"
    / "technology_summary_request_v1.json"
)


def fact_pack_payload() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def summary_payload() -> dict[str, object]:
    return {
        "tech_id": "spring-security",
        "headline": "인증 필터 체인을 직접 구성했다",
        "summary": "SecurityConfig 에서 SecurityFilterChain 을 정의했다.",
        "gap": "메서드 단위 보안을 켠 곳은 확인되지 않았다.",
        "used_highlights": [0, 1, 2, 3],
        "confidence": "HIGH",
    }


def test_fixture_fact_pack_is_valid() -> None:
    pack = FactPack.model_validate(fact_pack_payload())

    assert pack.technology.tech_id == "spring-security"
    assert pack.authorship is Authorship.MOSTLY_MINE
    assert pack.technology.personal_level is EvidenceLevel.L2
    assert len(pack.highlights) == 5


def test_fact_pack_rejects_unsupported_schema_version() -> None:
    payload = fact_pack_payload()
    payload["schema_version"] = "technology-summary-request/v2"

    with pytest.raises(ValidationError):
        FactPack.model_validate(payload)


def test_fact_pack_rejects_unknown_field() -> None:
    payload = fact_pack_payload()
    payload["evidence_count"] = 82

    with pytest.raises(ValidationError):
        FactPack.model_validate(payload)


def test_fact_pack_rejects_more_than_eight_highlights() -> None:
    payload = fact_pack_payload()
    highlight = deepcopy(payload["highlights"][0])
    payload["highlights"] = [
        {**deepcopy(highlight), "index": index, "value": f"call{index}"}
        for index in range(9)
    ]

    with pytest.raises(ValidationError):
        FactPack.model_validate(payload)


def test_fact_pack_rejects_indexes_out_of_array_order() -> None:
    payload = fact_pack_payload()
    payload["highlights"][0]["index"] = 4
    payload["highlights"][4]["index"] = 0

    with pytest.raises(ValidationError):
        FactPack.model_validate(payload)


def test_fact_pack_rejects_next_level_at_or_below_personal_level() -> None:
    payload = fact_pack_payload()
    payload["next_level"]["level"] = "L2"

    with pytest.raises(ValidationError):
        FactPack.model_validate(payload)


def test_fact_pack_accepts_absent_period_and_next_level() -> None:
    payload = fact_pack_payload()
    payload["period"] = None
    payload["next_level"] = None

    pack = FactPack.model_validate(payload)

    assert pack.period is None
    assert pack.next_level is None


def test_fact_pack_rejects_reversed_period() -> None:
    payload = fact_pack_payload()
    payload["period"] = {"first": "2025-08-19", "last": "2025-08-11", "months": 1}

    with pytest.raises(ValidationError):
        FactPack.model_validate(payload)


def test_highlight_file_keeps_only_the_last_two_segments() -> None:
    payload = fact_pack_payload()
    payload["highlights"][0]["file"] = (
        "src/main/java/com/example/config/SecurityConfig.java"
    )

    pack = FactPack.model_validate(payload)

    assert pack.highlights[0].file == "config/SecurityConfig.java"


@pytest.mark.parametrize(
    ("file_path", "expected"),
    [
        ("build.gradle", "build.gradle"),
        ("domain/Card.java", "domain/Card.java"),
        ("a/b/c/d.java", "c/d.java"),
        ("src\\main\\Config.java", "main/Config.java"),
        ("/src/main/Config.java", "main/Config.java"),
    ],
)
def test_shorten_file_path(file_path: str, expected: str) -> None:
    assert shorten_file_path(file_path) == expected


def test_shorten_file_path_rejects_blank() -> None:
    with pytest.raises(ValueError):
        shorten_file_path("/")


def test_summary_accepts_null_gap_at_highest_level() -> None:
    payload = summary_payload()
    payload["gap"] = None

    assert TechnologySummary.model_validate(payload).gap is None


def test_summary_rejects_headline_over_forty_characters() -> None:
    payload = summary_payload()
    payload["headline"] = "가" * 41

    with pytest.raises(ValidationError):
        TechnologySummary.model_validate(payload)


def test_summary_rejects_summary_over_two_hundred_characters() -> None:
    payload = summary_payload()
    payload["summary"] = "가" * 201

    with pytest.raises(ValidationError):
        TechnologySummary.model_validate(payload)


def test_summary_rejects_out_of_range_highlight_index() -> None:
    payload = summary_payload()
    payload["used_highlights"] = [0, 8]

    with pytest.raises(ValidationError):
        TechnologySummary.model_validate(payload)


def test_summary_rejects_unknown_confidence() -> None:
    payload = summary_payload()
    payload["confidence"] = "VERY_HIGH"

    with pytest.raises(ValidationError):
        TechnologySummary.model_validate(payload)


def test_summary_accepts_every_confidence_band() -> None:
    for band in Confidence:
        payload = summary_payload()
        payload["confidence"] = band.value

        assert TechnologySummary.model_validate(payload).confidence is band


def test_published_schema_file_matches_the_ollama_format_schema() -> None:
    expected = (
        json.dumps(technology_summary_json_schema(), ensure_ascii=False, indent=2)
        + "\n"
    )

    assert SCHEMA_PATH.read_text(encoding="utf-8") == expected


def test_ollama_format_schema_avoids_unsupported_grammar_keywords() -> None:
    serialized = json.dumps(technology_summary_json_schema())

    for keyword in ("$ref", "allOf", "anyOf", "oneOf", "pattern", "if", "then"):
        assert f'"{keyword}"' not in serialized
