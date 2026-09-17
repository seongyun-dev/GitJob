from hashlib import sha256
from pathlib import Path

import pytest
from job.classifier import classify_job_batch
from job.contracts import JobAnalysisInputBatch, JobPostingInput
from job.requirements import (
    JOB_REQUIRED_LEVEL_POLICY_VERSION,
    JOB_REQUIREMENTS_SCHEMA_VERSION,
    JobRequirements,
    RequirementKind,
    RequirementLevel,
    RequirementLevelEvidenceSource,
    UnresolvedReason,
    extract_job_requirements,
)
from JobKorea_Collector_V1.technology import extract_technology_mentions
from pydantic import ValidationError
from registry.contracts import load_registry
from registry.mapper import RegistryMapper

AI_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = AI_ROOT / "registry" / "data" / "technology_registry_20260911_4.json"


def test_worknet_duty_heading_ends_navigation_sections():
    result = _analyze(
        "복리후생\n전형방법\n기업정보\n모집요강\n직무내용\nJava 개발\n회사소개\nPython 기반 회사"
    )
    assert result.required == ()
    assert not result.unresolved


def test_general_body_heading_overrides_stale_required_source_marker():
    result = _analyze("자격요건\nJava 경험\n복리후생\nAWS 교육 지원")

    assert [clause.tech_ids for clause in result.required] == [("java",)]
    assert result.unresolved == ()


@pytest.mark.parametrize(
    "heading", ["담당업무", "주요업무", "직무내용", "responsibilities"]
)
def test_duty_headings_do_not_make_technical_work_a_requirement(heading):
    result = _analyze(f"{heading}\nReact 화면 개발\n회사소개\nPython 기반 회사")

    assert result.required == ()
    assert result.preferred == ()
    assert result.unresolved == ()


def test_numbered_conditions_have_one_source_span_each():
    result = _analyze("자격요건\n1. Java 경험\n2. Python, Docker 등을 활용")
    assert [clause.tech_ids for clause in result.required] == [
        ("docker",),
        ("java",),
        ("python",),
    ]
    assert all(len(clause.evidence_refs) == 1 for clause in result.required)
    assert len(result.unresolved) == 1


def _analyze(
    body: str,
    *,
    title: str = "백엔드 개발자",
    career_level: str | None = "신입",
    shared_evidence: bool = False,
    technology_mentions: list[dict] | None = None,
) -> JobRequirements:
    mentions = technology_mentions or [
        mention.model_dump(mode="json", by_alias=True)
        for mention in extract_technology_mentions(title, body)
    ]
    if shared_evidence:
        evidence_text = "\n".join(body.splitlines()[1:])
        for mention in mentions:
            mention["evidence_text"] = evidence_text
    record = JobPostingInput.model_validate(
        {
            "source_record_id": "requirements-job-1",
            "source_site": "JOBKOREA",
            "source_posting_id": "requirements-job-1",
            "source_url": "https://example.com/jobs/requirements-job-1",
            "company_name": "Example",
            "title": title,
            "raw_job_category": "백엔드/서버개발",
            "career_level": career_level,
            "region": "서울",
            "description_text": body,
            "body_status": "TEXT_AVAILABLE",
            "posting_status": "ACTIVE",
            "posted_at": "2026-09-01T00:00:00Z",
            "deadline": "2026-10-01T00:00:00Z",
            "collected_at": "2026-09-09T00:00:00Z",
            "content_hash": sha256(body.encode()).hexdigest(),
            "technology_mentions": mentions,
        }
    )
    batch = JobAnalysisInputBatch(
        schema_version="job-analysis-input/v1",
        dataset_snapshot_id="requirements-snapshot-1",
        pipeline_run_id="requirements-run-1",
        collector_version="collector/test",
        records=(record,),
    )
    mapper = RegistryMapper(
        load_registry(REGISTRY_PATH, repository_root=AI_ROOT.parent)
    )
    classification = classify_job_batch(batch, mapper).records[0]
    return extract_job_requirements(record, classification)


def test_independent_resolved_clauses_survive_an_unresolved_or_operand() -> None:
    body = (
        "자격요건\n"
        "Java 또는 Python 개발 경험\n"
        "Docker 운영 경험\n"
        "Java 또는 Cobol 사용 경험"
    )

    result = _analyze(body)

    assert [clause.tech_ids for clause in result.required] == [
        ("docker",),
        ("java", "python"),
    ]
    assert result.preferred == ()
    assert len(result.unresolved) == 1
    unresolved = result.unresolved[0]
    assert unresolved.requirement_kind is RequirementKind.REQUIRED
    assert unresolved.reason is UnresolvedReason.TECHNOLOGY_MAPPING_UNRESOLVED
    assert unresolved.known_tech_ids == ("java",)
    assert unresolved.raw_operands == ("Cobol",)
    assert unresolved.evidence.text == "Java 또는 Cobol 사용 경험"
    assert body[unresolved.evidence.char_start : unresolved.evidence.char_end] == (
        unresolved.evidence.text
    )


def test_required_and_preferred_or_groups_are_kept_separate() -> None:
    result = _analyze(
        "자격요건\nJava 및 Spring Boot 경험\n우대사항\nRedis 또는 Docker 경험"
    )

    assert [clause.tech_ids for clause in result.required] == [
        ("java",),
        ("spring-boot",),
    ]
    assert [clause.tech_ids for clause in result.preferred] == [
        ("docker", "redis"),
    ]
    assert result.unresolved == ()


def test_jobkorea_skill_section_preserves_inline_required_label() -> None:
    result = _analyze("담당업무\n서비스 개발\n스킬\nㆍ필수 : React, Java")

    assert [clause.tech_ids for clause in result.required] == [
        ("java",),
        ("react",),
    ]
    assert result.preferred == ()
    assert result.unresolved == ()


def test_same_line_known_requirements_survive_unknown_comma_operand() -> None:
    result = _analyze("자격요건\nJava, Cobol, Python 개발 경험")

    assert [clause.tech_ids for clause in result.required] == [
        ("java",),
        ("python",),
    ]
    assert len(result.unresolved) == 1
    assert result.unresolved[0].reason is UnresolvedReason.TECHNOLOGY_MAPPING_UNRESOLVED
    assert result.unresolved[0].known_tech_ids == ("java", "python")
    assert result.unresolved[0].raw_operands == ("Cobol",)


@pytest.mark.parametrize(
    ("raw_technology", "tech_id"),
    [
        ("SpringBoot", "spring-boot"),
        ("HTML5", "html"),
        ("CSS3", "css"),
        ("NodeJS", "nodejs"),
        ("React.js", "react"),
        ("Nest.js", "nestjs"),
        ("NextJS", "nextjs"),
    ],
)
def test_collector_owned_spelling_variants_map_to_registry_technology(
    raw_technology: str, tech_id: str
) -> None:
    result = _analyze(f"자격요건\n{raw_technology} 개발 경험")

    assert [clause.tech_ids for clause in result.required] == [(tech_id,)]
    assert result.unresolved == ()


def test_list_marker_is_not_part_of_short_language_mapping() -> None:
    body = "자격요건\nㆍC 개발 경험"
    result = _analyze(
        body,
        technology_mentions=[
            {
                "raw_technology": "ㆍC",
                "technology_id": "c",
                "requirement_type": "REQUIRED",
                "source_surface": "BODY",
                "evidence_section": "자격요건",
                "evidence_text": "ㆍC 개발 경험",
                "extraction_method": "RULE_BASED_V1",
            }
        ],
    )

    assert [clause.tech_ids for clause in result.required] == [("c",)]
    assert result.unresolved == ()


def test_repeated_logical_clause_merges_evidence_without_losing_mentions() -> None:
    result = _analyze(
        "자격요건\nJava 경험\n우대사항\nRedis 또는 Docker 경험\nRedis 또는 Docker 경험"
    )

    assert len(result.preferred) == 1
    clause = result.preferred[0]
    assert clause.tech_ids == ("docker", "redis")
    assert [evidence.text for evidence in clause.evidence_refs] == [
        "Redis 또는 Docker 경험",
        "Redis 또는 Docker 경험",
    ]
    assert len({evidence.char_start for evidence in clause.evidence_refs}) == 2
    assert (
        clause.evidence_refs[0].mention_indices
        == clause.evidence_refs[1].mention_indices
    )
    assert all(len(evidence.mention_indices) == 2 for evidence in clause.evidence_refs)


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        ("Java 경험은 필수가 아닙니다", UnresolvedReason.NEGATION_UNSUPPORTED),
        (
            "Java, Python, Docker 중 2가지 이상",
            UnresolvedReason.CARDINALITY_UNSUPPORTED,
        ),
        ("Java 및 Python 또는 Docker 경험", UnresolvedReason.LOGIC_UNSUPPORTED),
        ("Java/Python 개발 경험", UnresolvedReason.LOGIC_UNSUPPORTED),
        ("Java 외", UnresolvedReason.LOGIC_UNSUPPORTED),
    ],
)
def test_unsupported_grammar_is_retained_with_its_original_span(
    line: str, reason: UnresolvedReason
) -> None:
    body = f"자격요건\n{line}\nRedis 경험"

    result = _analyze(body)

    assert result.required[-1].tech_ids == ("redis",)
    assert len(result.unresolved) == 1
    assert result.unresolved[0].reason is reason
    assert result.unresolved[0].evidence.text == line
    start = result.unresolved[0].evidence.char_start
    end = result.unresolved[0].evidence.char_end
    assert start is not None and end is not None
    assert body[start:end] == line


def test_multiline_classifier_evidence_is_split_into_independent_source_lines() -> None:
    result = _analyze(
        "자격요건\nJava 경험\nPython, Docker 등을 활용",
        shared_evidence=True,
    )

    assert [clause.tech_ids for clause in result.required] == [
        ("docker",),
        ("java",),
        ("python",),
    ]
    assert len(result.unresolved) == 1
    assert result.unresolved[0].reason is UnresolvedReason.LOGIC_UNSUPPORTED
    assert result.unresolved[0].known_tech_ids == ("docker", "python")
    assert result.unresolved[0].evidence.text == "Python, Docker 등을 활용"


def test_simple_slash_preserves_known_technologies_without_inventing_logic() -> None:
    result = _analyze("자격요건\nJava/Python 개발 경험")

    assert [clause.tech_ids for clause in result.required] == [
        ("java",),
        ("python",),
    ]
    assert len(result.unresolved) == 1
    assert result.unresolved[0].reason is UnresolvedReason.LOGIC_UNSUPPORTED
    assert result.unresolved[0].known_tech_ids == ("java", "python")
    assert result.unresolved[0].evidence.text == "Java/Python 개발 경험"


def test_company_introduction_and_general_skill_sections_are_not_requirements() -> None:
    result = _analyze(
        "자격요건\nJava 경험\n"
        "기술스택\nPython\n"
        "회사소개\nKotlin 기반 서비스를 운영합니다"
    )

    assert [clause.tech_ids for clause in result.required] == [("java",)]
    assert result.preferred == ()
    assert result.unresolved == ()


def test_unlocated_required_evidence_is_unresolved_without_invented_offsets() -> None:
    body = "자격요건\nJava 경험"
    record = JobPostingInput.model_validate(
        {
            "source_record_id": "requirements-job-1",
            "source_site": "JOBKOREA",
            "source_posting_id": "requirements-job-1",
            "source_url": "https://example.com/jobs/requirements-job-1",
            "company_name": "Example",
            "title": "백엔드 개발자",
            "raw_job_category": "백엔드/서버개발",
            "career_level": "신입",
            "region": "서울",
            "description_text": body,
            "body_status": "TEXT_AVAILABLE",
            "posting_status": "ACTIVE",
            "posted_at": "2026-09-01T00:00:00Z",
            "deadline": "2026-10-01T00:00:00Z",
            "collected_at": "2026-09-09T00:00:00Z",
            "content_hash": sha256(body.encode()).hexdigest(),
            "technology_mentions": [
                {
                    "raw_technology": "Java",
                    "technology_id": None,
                    "requirement_type": "REQUIRED",
                    "source_surface": "BODY",
                    "evidence_section": "자격요건",
                    "evidence_text": "Java 실무 경험",
                    "extraction_method": "TEST_UNLOCATED",
                }
            ],
        }
    )
    batch = JobAnalysisInputBatch(
        schema_version="job-analysis-input/v1",
        dataset_snapshot_id="requirements-snapshot-1",
        pipeline_run_id="requirements-run-1",
        collector_version="collector/test",
        records=(record,),
    )
    mapper = RegistryMapper(
        load_registry(REGISTRY_PATH, repository_root=AI_ROOT.parent)
    )
    classification = classify_job_batch(batch, mapper).records[0]

    result = extract_job_requirements(record, classification)

    assert result.required == ()
    assert result.unresolved[0].reason is UnresolvedReason.EVIDENCE_NOT_LOCATED
    assert result.unresolved[0].evidence.char_start is None
    assert result.unresolved[0].evidence.char_end is None
    assert result.unresolved[0].evidence.text == "Java 실무 경험"


def test_output_is_frozen_round_trippable_and_bound_to_the_source_record() -> None:
    result = _analyze("자격요건\nJava 경험")

    assert JobRequirements.model_validate_json(result.model_dump_json()) == result
    with pytest.raises(ValidationError):
        result.required = ()


def test_required_level_contract_has_versioned_deterministic_lineage() -> None:
    result = _analyze("자격요건\nJava 실무 개발 경험")

    assert result.schema_version == JOB_REQUIREMENTS_SCHEMA_VERSION
    assert result.schema_version == "job-requirements/v2"
    assert result.level_policy_version == JOB_REQUIRED_LEVEL_POLICY_VERSION
    clause = result.required[0]
    assert clause.required_level is RequirementLevel.L2
    assert clause.level_evidence_refs[0].source is (
        RequirementLevelEvidenceSource.DIRECT_CLAUSE
    )
    assert clause.level_evidence_refs[0].text == "Java 실무 개발 경험"
    assert clause.level_evidence_refs[0].mention_indices == (0,)
    assert JobRequirements.model_validate_json(result.model_dump_json()) == result
    assert (
        result.model_dump_json()
        == _analyze("자격요건\nJava 실무 개발 경험").model_dump_json()
    )


@pytest.mark.parametrize(
    ("body", "career_level", "expected"),
    [
        ("자격요건\nJava 필수", "신입", RequirementLevel.L1),
        ("자격요건\nJava 경험", None, RequirementLevel.L2),
        ("자격요건\nJava 운영", "경력 1년 이상", RequirementLevel.L2),
        ("자격요건\nJava 서비스 설계", None, RequirementLevel.L2),
        ("자격요건\nJava 성능 최적화", None, RequirementLevel.L3),
        ("자격요건\nJava 운영 책임", None, RequirementLevel.L3),
        ("자격요건\nJava", "경력 5년 이상", RequirementLevel.L1),
        ("자격요건\nJava", "과장 이상", RequirementLevel.L1),
        ("자격요건\nJava 경력 3~7년", None, RequirementLevel.L2),
        ("자격요건\nJava 기초 이해", "경력 8년 이상", RequirementLevel.L1),
        ("자격요건\nJava 경험", "경력 8년 이상", RequirementLevel.L2),
        ("자격요건\nJava", "경력 0년", RequirementLevel.L1),
        ("자격요건\nPython을 활용한 개발이 가능한 분", None, RequirementLevel.L1),
        ("자격요건\nJava 사용이 가능하신 분", None, RequirementLevel.L1),
        ("자격요건\nDocker 기반 서비스 배포 및 운영 경험", None, RequirementLevel.L2),
    ],
)
def test_required_level_boundaries_are_conservative(
    body: str,
    career_level: str | None,
    expected: RequirementLevel,
) -> None:
    result = _analyze(body, career_level=career_level)

    assert result.required[0].required_level is expected


@pytest.mark.parametrize(
    ("body", "expected_levels"),
    [
        ("지원자격\n경력 5년 이상\nJava 필수", (RequirementLevel.L1,)),
        ("자격요건: 경력 5년 이상\nJava 필수", (RequirementLevel.L1,)),
        (
            "지원자격\n경력 5년 이상\nJava 필수\nPython 필수",
            (RequirementLevel.L1, RequirementLevel.L1),
        ),
        ("지원자격\n경력 5년 이상\nJava 경험", (RequirementLevel.L2,)),
    ],
)
def test_technology_free_section_career_does_not_escalate_technology_levels(
    body: str,
    expected_levels: tuple[RequirementLevel, ...],
) -> None:
    result = _analyze(body, career_level=None)

    assert tuple(clause.required_level for clause in result.required) == expected_levels
    assert all(
        evidence.source.value != "REQUIREMENT_SECTION"
        for clause in result.required
        for evidence in clause.level_evidence_refs
    )


@pytest.mark.parametrize(
    "line",
    [
        "Java 기초 이해, 경력 5년 이상",
        "Java 관련 지식, 경력 5년 이상",
        "Java 사용 가능, 경력 5년 이상",
        "Java 활용 가능, 경력 5년 이상",
        "Java 개발 가능, 경력 5년 이상",
    ],
)
def test_explicit_low_intensity_signal_blocks_unbound_year_escalation(
    line: str,
) -> None:
    result = _analyze(f"자격요건\n{line}", career_level=None)

    assert result.required[0].required_level is RequirementLevel.L1


def test_direct_technology_development_career_keeps_l3() -> None:
    result = _analyze("자격요건\nJava 개발 경력 5년 이상", career_level=None)

    assert result.required[0].required_level is RequirementLevel.L3


def test_level_signal_stays_bound_to_each_comma_separated_technology() -> None:
    result = _analyze(
        "지원자격\nJava 개발 경력 5년 이상, Python 개발 경험",
        career_level=None,
    )

    by_tech = {clause.tech_ids: clause.required_level for clause in result.required}
    assert by_tech == {
        ("java",): RequirementLevel.L3,
        ("python",): RequirementLevel.L2,
    }


def test_calibrated_open_list_preserves_known_technologies_but_duty_does_not():
    open_list = _analyze("지원자격\nJava, React, JPA 등의 개발 경험")
    parenthetical = _analyze(
        "지원자격\n주요 백엔드 프레임워크(Spring, Django, Node.js 등) 활용 경험"
    )
    duty = _analyze("담당업무\nJava Spring Boot REST API 설계 및 핵심 기능 개발")
    unrelated_optimization = _analyze("담당업무\nReact 이미지 최적화 경험")

    assert [clause.tech_ids for clause in open_list.required] == [
        ("java",),
        ("jpa",),
        ("react",),
    ]
    assert open_list.unresolved[0].reason is UnresolvedReason.LOGIC_UNSUPPORTED
    assert parenthetical.required == ()
    assert parenthetical.unresolved[0].reason is UnresolvedReason.LOGIC_UNSUPPORTED
    assert duty.required == ()
    assert duty.unresolved == ()
    assert unrelated_optimization.required == ()
    assert unrelated_optimization.unresolved == ()


@pytest.mark.parametrize(
    "text",
    [
        "Backend frameworks (Spring, Django, Node.js, etc.) experience",
        "백엔드 프레임워크(Spring/Django 등) 활용 경험",
    ],
)
def test_parenthetical_open_list_examples_are_not_promoted(text):
    result = _analyze(f"지원자격\n{text}")

    assert result.required == ()
    assert len(result.unresolved) == 1
    assert result.unresolved[0].reason is UnresolvedReason.LOGIC_UNSUPPORTED


def test_calibrated_title_and_structured_skill_signals_do_not_create_requirements():
    result = _analyze(
        "기술스택\nDocker 최적화",
        title="Java 경력 8년 아키텍처 리드",
        career_level="경력 8년 이상",
    )

    assert result.required == ()
    assert result.preferred == ()
    assert result.unresolved == ()


def test_calibrated_one_of_capability_is_one_l1_clause() -> None:
    result = _analyze("지원자격\nJava, Python, Docker 중 1개 이상 활용 가능")

    assert len(result.required) == 1
    assert result.required[0].tech_ids == ("docker", "java", "python")
    assert result.required[0].required_level is RequirementLevel.L1


def test_grade_range_in_a_technology_clause_remains_unresolved() -> None:
    result = _analyze("지원자격\nJava 대리~부장")

    assert result.required == ()
    assert result.unresolved[0].reason is UnresolvedReason.LOGIC_UNSUPPORTED


def test_unsupported_clause_stays_unresolved_without_inventing_a_level() -> None:
    result = _analyze("자격요건\nJava 및 Python 또는 Docker 경험")

    assert result.required == ()
    assert result.unresolved[0].reason is UnresolvedReason.LOGIC_UNSUPPORTED
    assert "UNKNOWN" not in {level.value for level in RequirementLevel}


def test_v1_payload_remains_readable_without_level_fields() -> None:
    current = _analyze("자격요건\nJava 경험")
    payload = current.model_dump(mode="json")
    payload["schema_version"] = "job-requirements/v1"
    payload.pop("level_policy_version")
    for clause in payload["required"]:
        clause.pop("required_level")
        clause.pop("level_evidence_refs")

    legacy = JobRequirements.model_validate(payload)

    assert legacy.schema_version == "job-requirements/v1"
    assert legacy.level_policy_version is None
    assert legacy.required[0].required_level is None
    assert "required_level" not in legacy.model_dump(mode="json")["required"][0]


def test_v2_contract_rejects_missing_level_or_policy_version() -> None:
    current = _analyze("자격요건\nJava 경험")
    payload = current.model_dump(mode="json")
    payload["required"][0].pop("required_level")

    with pytest.raises(ValidationError):
        JobRequirements.model_validate(payload)

    payload = current.model_dump(mode="json")
    payload.pop("level_policy_version")
    with pytest.raises(ValidationError):
        JobRequirements.model_validate(payload)

    payload = current.model_dump(mode="json")
    payload["required"][0]["required_level"] = "L3"
    with pytest.raises(ValidationError):
        JobRequirements.model_validate(payload)

    payload = current.model_dump(mode="json")
    payload["required"][0]["level_evidence_refs"][0]["mention_indices"] = [99]
    with pytest.raises(ValidationError):
        JobRequirements.model_validate(payload)


def test_committed_a_to_c_fixture_runs_through_the_current_classifier() -> None:
    fixture = JobAnalysisInputBatch.model_validate_json(
        (AI_ROOT / "job/fixtures/job_analysis_input_v1.json").read_text(
            encoding="utf-8"
        )
    )
    mapper = RegistryMapper(
        load_registry(REGISTRY_PATH, repository_root=AI_ROOT.parent)
    )
    classified = classify_job_batch(fixture, mapper)

    result = extract_job_requirements(fixture.records[0], classified.records[0])

    assert result.source_record_id == "jobkorea:fixture-1001"
    assert result.required[0].tech_ids == ("csharp",)
    assert result.required[0].required_level is RequirementLevel.L2
    evidence = result.required[0].evidence_refs[0]
    assert fixture.records[0].description_text is not None
    assert (
        fixture.records[0].description_text[evidence.char_start : evidence.char_end]
        == evidence.text
    )
