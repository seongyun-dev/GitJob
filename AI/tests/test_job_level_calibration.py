"""Intensity calibration: preserve source scope, old decisions, and uncertainty."""

import json
from pathlib import Path

import pytest
import test_job_requirements
from pydantic import ValidationError
from test_job_requirements import _analyze

from job.requirements import JobRequirements, RequirementLevel, UnresolvedReason


@pytest.mark.parametrize(
    "line",
    [
        "React 능숙",
        "React를 능숙하게 사용하실 수 있는 분",
        "Java에 대한 깊은 이해와 관련 지식",
        "Python 전문 지식을 보유하신 분",
        "Java 사용에 능통하신 분",
        "Proficiency in React",
        "Able to use React proficiently",
        "Deep understanding of Java",
    ],
)
def test_explicit_proficiency_overrides_generic_capability(line):
    body = f"자격요건\n{line}"
    result = _analyze(body)
    assert len(result.required) == 1
    clause = result.required[0]
    assert clause.required_level is RequirementLevel.L3
    for ref in clause.level_evidence_refs:
        assert body[ref.char_start : ref.char_end] == ref.text


def test_real_worknet_proficient_list_has_shared_intensity(monkeypatch):
    # Exact clause in WORKNET:K120312608040027 (2026-09-08 input).
    # HTML/CSS were added after the legacy registry used by the common helper.
    monkeypatch.setattr(
        test_job_requirements,
        "REGISTRY_PATH",
        Path(__file__).parents[1] / "registry/data/technology_registry_20260911_1.json",
    )
    result = _analyze("자격요건\nHTML, CSS, JavaScript을 능숙하게 사용하실 수 있는 분")
    assert {tech for clause in result.required for tech in clause.tech_ids} == {
        "html",
        "css",
        "javascript",
    }
    assert all(
        clause.required_level is RequirementLevel.L3 for clause in result.required
    )


@pytest.mark.parametrize(
    "line",
    [
        "React에 능숙하지 않아도 지원 가능",
        "React에 능숙하지 않으셔도 지원 가능",
        "React 숙련자가 아니어도 지원 가능",
        "React에 숙련되지 않아도 지원 가능",
        "Not proficient in React",
        "React proficiency is not required",
        "No React proficiency required",
        "React 능숙할 필요 없음",
        "React 능숙할 필요가 없음",
        "React 숙련도를 요구하지 않음",
    ],
)
def test_negated_proficiency_remains_unresolved(line):
    result = _analyze(f"자격요건\n{line}")
    assert not result.required
    assert result.unresolved[0].reason is UnresolvedReason.NEGATION_UNSUPPORTED


@pytest.mark.parametrize(
    "line",
    [
        "Java 미숙련자도 지원 가능",
        "You do not need to be proficient in React",
        "You don't need to be proficient in React",
        "You need not be proficient in React",
        "Java 미숙련자 지원 허용",
        "Java에 미숙련인 지원자도 지원할 수 있습니다",
    ],
)
def test_applicant_proficiency_exemptions_remain_unresolved(line):
    result = _analyze(f"자격요건\n{line}")

    assert not result.required
    assert len(result.unresolved) == 1
    assert result.unresolved[0].reason is UnresolvedReason.NEGATION_UNSUPPORTED


@pytest.mark.parametrize(
    "line",
    [
        "Java 미숙련 동료와 협업 경험",
        "Experience mentoring novice Java engineers",
    ],
)
def test_novice_colleague_wording_is_not_applicant_negation(line):
    result = _analyze(f"자격요건\n{line}")

    assert not result.unresolved
    assert result.required[0].required_level is RequirementLevel.L2


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("React 기초 지식", "L1"),
        ("React 사용 가능", "L1"),
        ("React 개발 경험", "L2"),
        ("Java 전문가와 협업 경험", "L2"),
        ("Java 최적화의 기본 지식", "L1"),
        ("React 기초 사용에 능숙", "L1"),
    ],
)
def test_generic_use_or_expert_colleague_does_not_imply_proficiency(line, expected):
    result = _analyze(f"자격요건\n{line}")
    assert result.required[0].required_level.value == expected


@pytest.mark.parametrize(
    "line",
    [
        "React에 능숙한 동료와 협업 경험",
        "React에 숙련된 팀원과 개발 경험",
        "Experience collaborating with engineers proficient in React",
        "Experience working with colleagues who are proficient in React",
        "Experience collaborating with proficient React engineers",
    ],
)
def test_colleague_proficiency_is_not_applicant_proficiency(line):
    result = _analyze(f"자격요건\n{line}")

    assert not result.unresolved
    assert result.required[0].required_level is RequirementLevel.L2


@pytest.mark.parametrize(
    "line",
    [
        "React에 능숙하며 동료와 협업 경험",
        "React에 능숙한 개발자",
        "React engineers must be proficient",
    ],
)
def test_applicant_proficiency_stays_l3_near_collaboration_wording(line):
    result = _analyze(f"자격요건\n{line}")

    assert result.required[0].required_level is RequirementLevel.L3


def test_proficiency_is_bound_to_independent_technology_clause():
    result = _analyze("자격요건\nReact 능숙, Java 기초 지식")
    assert {c.tech_ids: c.required_level.value for c in result.required} == {
        ("react",): "L3",
        ("java",): "L1",
    }


def test_leading_proficiency_does_not_leak_into_a_following_bare_technology():
    result = _analyze("자격요건\nReact 능숙, Java")
    assert {c.tech_ids: c.required_level.value for c in result.required} == {
        ("react",): "L3",
        ("java",): "L1",
    }


def test_independent_intensity_precedes_a_shared_multi_technology_condition():
    line = "React 능숙, Java와 Python 개발 경험"
    result = _analyze(f"자격요건\n{line}")
    clauses = {clause.tech_ids: clause for clause in result.required}

    assert {key: clause.required_level.value for key, clause in clauses.items()} == {
        ("react",): "L3",
        ("java",): "L2",
        ("python",): "L2",
    }
    assert clauses[("react",)].level_evidence_refs[0].text == "React 능숙"
    assert clauses[("java",)].level_evidence_refs[0].text == "Java와 Python 개발 경험"
    assert (
        clauses[("python",)].level_evidence_refs[0].text
        == clauses[("java",)].level_evidence_refs[0].text
    )
    assert clauses[("react",)].evidence_refs[0].mention_indices == (0,)
    assert clauses[("java",)].evidence_refs[0].mention_indices == (1,)
    assert clauses[("python",)].evidence_refs[0].mention_indices == (2,)
    body = f"자격요건\n{line}"
    for clause in clauses.values():
        evidence = clause.evidence_refs[0]
        assert body[evidence.char_start : evidence.char_end] == evidence.text


def test_internal_technology_list_keeps_its_shared_trailing_condition():
    result = _analyze("자격요건\nJava와 Python 개발 경험")

    assert {
        clause.tech_ids: clause.required_level.value for clause in result.required
    } == {
        ("java",): "L2",
        ("python",): "L2",
    }


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        (
            "React 능숙, Java 또는 Python 개발 경험",
            UnresolvedReason.LOGIC_UNSUPPORTED,
        ),
        (
            "React 능숙, Java와 Python 중 2가지 이상",
            UnresolvedReason.CARDINALITY_UNSUPPORTED,
        ),
        (
            "React 능숙, Java와 Python 경험 불필요",
            UnresolvedReason.NEGATION_UNSUPPORTED,
        ),
    ],
)
def test_multi_technology_fragment_does_not_relax_unresolved_logic(line, reason):
    result = _analyze(f"자격요건\n{line}")

    assert not result.required
    assert result.unresolved[0].reason is reason


@pytest.mark.parametrize(
    "line", ["Java 경험, 총 경력 10년 이상", "Java 경험, 전체 경력 10년 이상"]
)
def test_explicit_overall_career_does_not_promote_a_technology(line):
    result = _analyze(f"자격요건\n{line}")
    assert result.required[0].required_level is RequirementLevel.L2


def test_shared_trailing_experience_survives_overall_career_suffix():
    result = _analyze("자격요건\nJava, Python 개발 경험, 총 경력 10년 이상")
    assert {c.tech_ids: c.required_level.value for c in result.required} == {
        ("java",): "L2",
        ("python",): "L2",
    }


@pytest.mark.parametrize(
    "line",
    [
        "주요 백엔드 프레임워크(Spring, Django, Node.js 등) 활용 경험",
        "일정이상의 프로그래밍 언어 사용 능력(Python 등)",
        "개발 경험 [Java 등]",
    ],
)
def test_real_parenthesized_open_lists_do_not_become_independent_requirements(line):
    result = _analyze(f"자격요건\n{line}")
    assert not result.required
    assert result.unresolved[0].reason is UnresolvedReason.LOGIC_UNSUPPORTED


def test_grade_word_is_not_an_open_list_marker():
    result = _analyze("자격요건\nJava 등급 평가 개발 경험")
    assert result.required[0].required_level is RequirementLevel.L2


def test_parenthesized_education_word_is_not_an_open_list_marker():
    result = _analyze("자격요건\n학력(고등) Java 개발 경험")
    assert result.required[0].required_level is RequirementLevel.L2


def test_proficiency_does_not_change_section_semantics():
    result = _analyze(
        "담당업무\nJava 최적화\n우대사항\nReact 능숙\n회사소개\nPython 전문가"
    )
    assert not result.required
    assert len(result.preferred) == 1
    assert result.preferred[0].tech_ids == ("react",)
    assert result.preferred[0].required_level is None


def test_new_policy_is_recorded_and_unknown_policy_fails_closed():
    result = _analyze("자격요건\nReact 능숙")
    assert result.level_policy_version == "job-required-level-policy/v2"
    payload = result.model_dump(mode="json")
    payload["level_policy_version"] = "job-required-level-policy/v999"
    with pytest.raises(ValidationError):
        JobRequirements.model_validate(payload)


def test_base_generated_policy_v1_decisions_round_trip_without_recalculation():
    path = Path(__file__).parent / "fixtures/job-level-policy-v1-base-3a4c57c.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    results = [
        JobRequirements.model_validate(payload) for payload in fixture["requirements"]
    ]
    assert [r.required[0].required_level.value for r in results] == ["L1", "L2"]
    assert all(
        r.level_policy_version == "job-required-level-policy/v1" for r in results
    )
    assert [r.model_dump(mode="json") for r in results] == fixture["requirements"]
