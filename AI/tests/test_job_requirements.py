from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from job.classifier import classify_job_batch
from job.contracts import JobAnalysisInputBatch, JobPostingInput
from job.requirements import (
    JobRequirements,
    RequirementKind,
    UnresolvedReason,
    extract_job_requirements,
)
from JobKorea_Collector_V1.technology import extract_technology_mentions
from registry.contracts import load_registry
from registry.mapper import RegistryMapper

AI_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = AI_ROOT / "registry" / "data" / "technology_registry_v1.json"


def test_worknet_duty_heading_ends_navigation_sections():
    result = _analyze(
        "복리후생\n전형방법\n기업정보\n모집요강\n직무내용\nJava 개발\n회사소개\nPython 기반 회사"
    )
    assert [c.tech_ids for c in result.required] == [("java",)]
    assert not result.unresolved


@pytest.mark.parametrize(
    "heading", ["담당업무", "주요업무", "직무내용", "responsibilities"]
)
def test_supported_duty_headings_make_technical_work_required(heading):
    result = _analyze(f"{heading}\nReact 화면 개발\n회사소개\nPython 기반 회사")

    assert [clause.tech_ids for clause in result.required] == [("react",)]
    assert result.preferred == ()
    assert result.unresolved == ()


def test_numbered_conditions_have_one_source_span_each():
    result = _analyze("자격요건\n1. Java 경험\n2. Python, Docker 등을 활용")
    assert len(result.required) == 1
    assert len(result.required[0].evidence_refs) == 1
    assert len(result.unresolved) == 1


def _analyze(
    body: str,
    *,
    title: str = "백엔드 개발자",
    shared_evidence: bool = False,
) -> JobRequirements:
    mentions = [
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
            "career_level": "신입",
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

    assert [clause.tech_ids for clause in result.required] == [("java",)]
    assert len(result.unresolved) == 1
    assert result.unresolved[0].reason is UnresolvedReason.LOGIC_UNSUPPORTED
    assert result.unresolved[0].known_tech_ids == ("docker", "python")
    assert result.unresolved[0].evidence.text == "Python, Docker 등을 활용"


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
    evidence = result.required[0].evidence_refs[0]
    assert fixture.records[0].description_text is not None
    assert (
        fixture.records[0].description_text[evidence.char_start : evidence.char_end]
        == evidence.text
    )
