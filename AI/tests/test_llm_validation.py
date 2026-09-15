import json
from pathlib import Path

import pytest

from llm.contracts import Confidence, FactPack, TechnologySummary
from llm.validation import (
    derive_confidence,
    fallback_summary,
    validate_summary,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "llm"
    / "fixtures"
    / "technology_summary_request_v1.json"
)


def fact_pack(**overrides: object) -> FactPack:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload.update(overrides)
    return FactPack.model_validate(payload)


def summary(**overrides: object) -> TechnologySummary:
    payload: dict[str, object] = {
        "tech_id": "spring-security",
        "headline": "인증 필터 체인을 직접 구성했다",
        "summary": (
            "SecurityConfig 에서 SecurityFilterChain 을 정의하고 "
            "authorizeHttpRequests 로 요청별 인가 규칙을 설정했다."
        ),
        "gap": "EnableMethodSecurity 를 켠 곳은 확인되지 않았다.",
        "used_highlights": [0, 1],
        "confidence": "HIGH",
    }
    payload.update(overrides)
    return TechnologySummary.model_validate(payload)


def codes(*args: object) -> tuple[str, ...]:
    return tuple(failure.code for failure in validate_summary(*args))


def test_grounded_summary_passes() -> None:
    assert validate_summary(summary(), fact_pack()) == ()


def test_summary_for_another_technology_is_discarded() -> None:
    assert "TECH_ID_MISMATCH" in codes(summary(tech_id="spring-boot"), fact_pack())


def test_out_of_range_highlight_index_is_discarded() -> None:
    assert "HIGHLIGHT_INDEX_OUT_OF_RANGE" in codes(
        summary(used_highlights=[0, 7]), fact_pack()
    )


@pytest.mark.parametrize(
    "text",
    ["근거의 73% 가 본인 것이다.", "본인 비율이 높다.", "퍼센트로 보면 많다."],
)
def test_ratio_wording_is_discarded(text: str) -> None:
    assert "RATIO_MENTIONED" in codes(summary(gap=text), fact_pack())


@pytest.mark.parametrize("text", ["고급 수준으로 다뤘다.", "숙련된 사용이다."])
def test_grade_words_are_discarded(text: str) -> None:
    assert "GRADE_WORD" in codes(summary(gap=text), fact_pack())


def test_level_string_in_the_body_is_discarded() -> None:
    assert "LEVEL_STRING_IN_BODY" in codes(
        summary(headline="L2 수준으로 사용했다"), fact_pack()
    )


def test_authorship_claim_is_discarded_when_contribution_was_not_judged() -> None:
    pack = fact_pack(authorship="NOT_VERIFIED")

    assert "UNVERIFIED_AUTHORSHIP_CLAIM" in codes(
        summary(headline="인증 필터 체인을 직접 작성했다"), pack
    )


def test_the_same_claim_is_allowed_when_contribution_was_judged() -> None:
    assert "UNVERIFIED_AUTHORSHIP_CLAIM" not in codes(
        summary(headline="인증 필터 체인을 직접 작성했다"), fact_pack()
    )


def test_invented_api_name_is_discarded() -> None:
    failures = validate_summary(
        summary(summary="WebSecurityConfigurerAdapter 를 상속해 설정했다."),
        fact_pack(),
    )

    assert [failure.code for failure in failures] == ["UNGROUNDED_IDENTIFIER"]
    assert "WebSecurityConfigurerAdapter" in failures[0].detail


def test_names_taken_from_the_fact_pack_are_grounded() -> None:
    grounded = summary(
        summary="passwordEncoder 와 org.springframework.security.web 가 쓰였다.",
        gap="EnableMethodSecurity 가 없다.",
    )

    assert validate_summary(grounded, fact_pack()) == ()


def test_file_name_with_extension_taken_from_fact_pack_is_grounded() -> None:
    grounded = summary(summary="SecurityConfig.java 에서 인가 규칙을 설정했다.")

    assert "UNGROUNDED_IDENTIFIER" not in codes(grounded, fact_pack())


def test_wildcard_name_copied_from_next_level_is_grounded() -> None:
    pack = fact_pack(
        next_level={
            "level": "L3",
            "rule": "Lombok import",
            "missing": ["lombok.* import"],
        }
    )
    grounded = summary(gap="lombok.* import 를 쓴 곳이 확인되지 않았다.")

    assert "UNGROUNDED_IDENTIFIER" not in codes(grounded, pack)


def test_repository_name_counts_as_grounded() -> None:
    grounded = summary(summary="card-service-backend 에서 확인됐다.")

    assert validate_summary(grounded, fact_pack()) == ()


def test_every_failure_is_reported_not_just_the_first() -> None:
    reported = codes(
        summary(
            headline="L3 고급 수준이다",
            summary="ReactiveSecurity 를 썼다.",
            tech_id="spring-boot",
        ),
        fact_pack(),
    )

    assert set(reported) >= {
        "TECH_ID_MISMATCH",
        "GRADE_WORD",
        "LEVEL_STRING_IN_BODY",
        "UNGROUNDED_IDENTIFIER",
    }


def test_confidence_is_high_when_the_person_wrote_an_api_call() -> None:
    assert derive_confidence(fact_pack()) is Confidence.HIGH


def test_confidence_is_medium_when_only_imports_are_the_persons() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["highlights"] = [
        {
            "index": 0,
            "fact_type": "IMPORT",
            "value": "org.springframework.security.web",
            "file": "filter/JwtAuthenticationFilter.java",
            "mine": True,
        }
    ]

    assert derive_confidence(FactPack.model_validate(payload)) is Confidence.MEDIUM


def test_confidence_is_low_without_judged_contribution() -> None:
    assert derive_confidence(fact_pack(authorship="NOT_VERIFIED")) is Confidence.LOW


def test_confidence_is_low_without_highlights() -> None:
    assert derive_confidence(fact_pack(highlights=[])) is Confidence.LOW


def test_fallback_summary_passes_the_length_and_id_checks() -> None:
    pack = fact_pack()
    generated = fallback_summary(pack)

    assert generated.tech_id == pack.technology.tech_id
    assert len(generated.headline) <= 40
    assert len(generated.summary) <= 200
    assert generated.gap is not None


def test_fallback_summary_has_no_gap_at_the_highest_level() -> None:
    assert fallback_summary(fact_pack(next_level=None)).gap is None


def test_fallback_summary_does_not_assert_authorship_when_not_verified() -> None:
    generated = fallback_summary(fact_pack(authorship="NOT_VERIFIED"))

    assert "확인되지 않았다" in generated.summary
    assert "본인이" not in generated.summary
    assert generated.confidence is Confidence.LOW


def test_missing_gap_is_discarded_when_a_next_level_exists() -> None:
    assert "GAP_MISSING" in codes(summary(gap=None), fact_pack())


@pytest.mark.parametrize("gap", ["", "   "])
def test_blank_gap_is_discarded_when_a_next_level_exists(gap: str) -> None:
    assert "GAP_MISSING" in codes(summary(gap=gap), fact_pack())


def test_gap_is_discarded_when_the_technology_is_at_its_highest_level() -> None:
    assert "GAP_WITHOUT_NEXT_LEVEL" in codes(summary(), fact_pack(next_level=None))


def test_null_gap_passes_at_the_highest_level() -> None:
    assert validate_summary(summary(gap=None), fact_pack(next_level=None)) == ()


@pytest.mark.parametrize(
    "fact_type",
    ["API_CALL", "ANNOTATION", "SYNTAX_NODE", "CONFIG_KEY"],
)
def test_confidence_is_high_for_every_implementation_fact_type(fact_type: str) -> None:
    pack = fact_pack(
        highlights=[
            {
                "index": 0,
                "fact_type": fact_type,
                "value": "EnableMethodSecurity",
                "file": "config/SecurityConfig.java",
                "mine": True,
            }
        ]
    )

    assert derive_confidence(pack) is Confidence.HIGH


@pytest.mark.parametrize("fact_type", ["IMPORT", "SOURCE_FILE", "DEPENDENCY"])
def test_confidence_is_medium_for_declaration_only_evidence(fact_type: str) -> None:
    pack = fact_pack(
        highlights=[
            {
                "index": 0,
                "fact_type": fact_type,
                "value": "org.springframework.security.web",
                "file": "config/SecurityConfig.java",
                "mine": True,
            }
        ]
    )

    assert derive_confidence(pack) is Confidence.MEDIUM
