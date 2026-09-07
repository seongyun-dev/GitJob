import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from job.classifier import (
    JOB_CLASSIFICATION_SCHEMA_VERSION,
    JOB_REQUIREMENT_PARSER_VERSION,
    JobClassificationBatch,
    RequirementClass,
    classify_job_batch,
)
from job.contracts import JobAnalysisInputBatch
from JobKorea_Collector_V1.technology import extract_technology_mentions
from registry.contracts import load_registry
from registry.mapper import MapperSource, MatchStatus, RegistryMapper

AI_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = AI_ROOT / "job" / "fixtures"
REGISTRY_PATH = AI_ROOT / "registry" / "data" / "technology_registry_v1.json"


def load_mapper() -> RegistryMapper:
    return RegistryMapper(load_registry(REGISTRY_PATH, repository_root=AI_ROOT.parent))


def load_fixture_payload() -> dict[str, object]:
    return json.loads(
        (FIXTURE_ROOT / "job_analysis_input_v1.json").read_text(encoding="utf-8")
    )


def test_committed_a_to_c_fixture_produces_expected_c_classifications() -> None:
    input_batch = JobAnalysisInputBatch.model_validate_json(
        json.dumps(load_fixture_payload())
    )
    expected = json.loads(
        (FIXTURE_ROOT / "job_analysis_expected_v1.json").read_text(encoding="utf-8")
    )

    output = classify_job_batch(input_batch, load_mapper())
    actual = {
        (record.source_record_id, result.raw_technology): result
        for record in output.records
        for result in record.technologies
    }

    assert output.schema_version == JOB_CLASSIFICATION_SCHEMA_VERSION
    assert output.input_schema_version == "job-analysis-input/v1"
    assert output.parser_version == JOB_REQUIREMENT_PARSER_VERSION
    assert output.registry_version == "registry-20260901.1"
    assert len(actual) == len(expected["cases"])
    for case in expected["cases"]:
        result = actual[(case["source_record_id"], case["raw_technology"])]
        assert result.tech_id == case["expected_tech_id"]
        assert result.match_status.value == case["expected_match_status"]
        assert result.requirement_class.value == case["expected_requirement_class"]
        assert result.evidence_text
        assert result.parser_version == JOB_REQUIREMENT_PARSER_VERSION


def test_c_output_preserves_demand_aggregation_and_lineage_dimensions() -> None:
    input_batch = JobAnalysisInputBatch.model_validate_json(
        json.dumps(load_fixture_payload())
    )

    output = classify_job_batch(input_batch, load_mapper())
    first = output.records[0]

    assert first.canonical_job_id == "fixture-job-001"
    assert str(first.source_url) == "https://example.invalid/jobs/fixture-1001"
    assert first.company_name == "Fixture Labs"
    assert first.title == "C# 백엔드 개발자"
    assert first.raw_job_category == "백엔드 개발"
    assert first.career_level == "경력 3년 이상"
    assert first.region == "서울"
    assert first.posting_status.value == "ACTIVE"
    assert first.posted_at.isoformat() == "2026-08-20T00:00:00+09:00"
    assert first.collected_at.isoformat() == "2026-08-31T00:00:00+00:00"
    assert first.content_hash == "a" * 64


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("source_url", "not-a-url"),
        ("posted_at", "2026-08-20T00:00:00"),
        ("collected_at", "2026-08-31T00:00:00"),
    ),
)
def test_serialized_c_output_rejects_weakened_source_invariants(
    field: str,
    invalid_value: str,
) -> None:
    input_batch = JobAnalysisInputBatch.model_validate_json(
        json.dumps(load_fixture_payload())
    )
    payload = classify_job_batch(input_batch, load_mapper()).model_dump(mode="json")
    payload["records"][0][field] = invalid_value

    with pytest.raises(ValidationError):
        JobClassificationBatch.model_validate(payload)


def test_evidence_location_is_preserved_against_the_original_surface() -> None:
    input_batch = JobAnalysisInputBatch.model_validate_json(
        json.dumps(load_fixture_payload())
    )

    output = classify_job_batch(input_batch, load_mapper())
    csharp = output.records[0].technologies[0]
    short_c = output.records[2].technologies[0]

    assert csharp.evidence_section == "자격요건"
    assert csharp.evidence_text == "C# 실무 경험"
    assert csharp.location.source_surface.value == "BODY"
    assert csharp.location.char_start == 6
    assert csharp.location.char_end == 14
    assert short_c.location.char_start == 0
    assert short_c.location.char_end == len("C·R·Go 데이터 플랫폼 엔지니어")


def test_mapper_fallback_attempts_are_preserved_in_order() -> None:
    input_batch = JobAnalysisInputBatch.model_validate_json(
        json.dumps(load_fixture_payload())
    )

    output = classify_job_batch(input_batch, load_mapper())
    csharp = output.records[0].technologies[0]
    short_c = output.records[2].technologies[0]

    assert [attempt.source for attempt in csharp.mapping_attempts] == [
        MapperSource.ALIAS
    ]
    assert [attempt.source for attempt in short_c.mapping_attempts] == [
        MapperSource.ALIAS,
        MapperSource.DISPLAY_NAME,
    ]
    assert [attempt.status for attempt in short_c.mapping_attempts] == [
        MatchStatus.UNKNOWN,
        MatchStatus.AMBIGUOUS,
    ]


def test_conflicting_explicit_requirement_and_section_requires_review() -> None:
    payload = load_fixture_payload()
    mention = payload["records"][0]["technology_mentions"][0]  # type: ignore[index]
    mention["evidence_section"] = "우대사항"  # type: ignore[index]
    input_batch = JobAnalysisInputBatch.model_validate_json(json.dumps(payload))

    output = classify_job_batch(input_batch, load_mapper())
    result = output.records[0].technologies[0]

    assert result.match_status is MatchStatus.MATCHED
    assert result.requirement_class is RequirementClass.REVIEW_REQUIRED
    assert result.classification_reason == "input requirement conflicts with section"


def test_section_boundary_classifies_mentioned_technology() -> None:
    payload = load_fixture_payload()
    mention = payload["records"][1]["technology_mentions"][1]  # type: ignore[index]
    mention["evidence_section"] = "필수 역량"  # type: ignore[index]
    input_batch = JobAnalysisInputBatch.model_validate_json(json.dumps(payload))

    result = classify_job_batch(input_batch, load_mapper()).records[1].technologies[1]

    assert result.requirement_class is RequirementClass.REQUIRED
    assert result.classification_reason == "section boundary supplied requirement"


def test_multiple_evidence_mentions_for_one_technology_are_not_collapsed() -> None:
    payload = load_fixture_payload()
    record = payload["records"][1]  # type: ignore[index]
    record["description_text"] += ". Node.js 운영 경험"  # type: ignore[index]
    record["technology_mentions"].append(  # type: ignore[index]
        {
            "raw_technology": "Node.js",
            "technology_id": "node.js",
            "requirement_type": "MENTIONED",
            "source_surface": "BODY",
            "evidence_section": "기술스택",
            "evidence_text": "Node.js 운영 경험",
            "extraction_method": "FIXTURE_RULE",
        }
    )
    input_batch = JobAnalysisInputBatch.model_validate_json(json.dumps(payload))

    output = classify_job_batch(input_batch, load_mapper())
    node_results = [
        result
        for result in output.records[1].technologies
        if result.tech_id == "nodejs"
    ]

    assert len(node_results) == 2
    assert {result.evidence_text for result in node_results} == {
        "Node.js 프로젝트 경험",
        "Node.js 운영 경험",
    }
    assert all(result.location.char_start is not None for result in node_results)


def test_identical_evidence_mentions_keep_distinct_indices_and_occurrences() -> None:
    payload = load_fixture_payload()
    record = payload["records"][3]  # type: ignore[index]
    repeated = dict(record["technology_mentions"][0])  # type: ignore[index]
    record["description_text"] = "QuantumDB 경험. QuantumDB 경험."  # type: ignore[index]
    record["technology_mentions"] = [repeated, dict(repeated)]  # type: ignore[index]
    input_batch = JobAnalysisInputBatch.model_validate_json(json.dumps(payload))

    results = classify_job_batch(input_batch, load_mapper()).records[3].technologies

    assert [result.mention_index for result in results] == [0, 1]
    assert [result.location.char_start for result in results] == [0, 14]
    assert [result.location.char_end for result in results] == [12, 26]


def test_non_text_records_remain_visible_with_empty_classifications() -> None:
    input_batch = JobAnalysisInputBatch.model_validate_json(
        json.dumps(load_fixture_payload())
    )

    output = classify_job_batch(input_batch, load_mapper())
    records_by_id = {record.source_record_id: record for record in output.records}

    assert records_by_id["jobplanet:fixture-1005"].body_status == "IMAGE_ONLY"
    assert records_by_id["jobplanet:fixture-1005"].technologies == ()
    assert records_by_id["jobkorea:fixture-1006"].body_status == "MISSING"
    assert records_by_id["jobkorea:fixture-1006"].technologies == ()


def test_collector_mentions_are_classified_from_full_section_boundaries() -> None:
    payload = load_fixture_payload()
    record = payload["records"][0]
    body = (
        "자격 요건\n"
        + "협업 역량과 문제 해결 경험\n" * 15
        + "Python 서비스 개발\n우대사항\nDocker 운영 경험\n"
        + "담당업무\nPostgreSQL 데이터 관리\n"
    )
    record["title"] = "백엔드 개발자"
    record["description_text"] = body
    record["technology_mentions"] = [
        mention.model_dump(mode="json", by_alias=True)
        for mention in extract_technology_mentions(record["title"], body)
    ]
    batch = JobAnalysisInputBatch.model_validate(payload)
    before = batch.model_dump_json()

    results = classify_job_batch(batch, load_mapper()).records[0].technologies
    by_raw = {result.raw_technology: result for result in results}

    assert by_raw["Python"].requirement_class is RequirementClass.REQUIRED
    assert by_raw["Python"].parsed_section == "자격 요건"
    assert by_raw["Docker"].requirement_class is RequirementClass.PREFERRED
    # The collector carries the earlier preferred signal across this boundary.
    # C treats responsibilities as required while retaining the collector input.
    assert by_raw["PostgreSQL"].requirement_class is RequirementClass.REQUIRED
    assert by_raw["PostgreSQL"].input_requirement_type == "PREFERRED"
    assert by_raw["PostgreSQL"].parsed_section == "담당업무"
    assert batch.model_dump_json() == before


def test_technologies_in_one_evidence_line_share_its_location() -> None:
    payload = load_fixture_payload()
    record = payload["records"][0]
    record["title"] = "백엔드 개발자"
    record["description_text"] = "자격요건\nPython, Docker 실무 경험"
    record["technology_mentions"] = [
        mention.model_dump(mode="json", by_alias=True)
        for mention in extract_technology_mentions(
            record["title"], record["description_text"]
        )
    ]
    batch = JobAnalysisInputBatch.model_validate(payload)

    results = classify_job_batch(batch, load_mapper()).records[0].technologies

    assert len(results) == 2
    assert all(result.location.char_start == 5 for result in results)
    assert all(
        result.requirement_class is RequirementClass.REQUIRED for result in results
    )


def classify_collector_body(body: str):
    payload = load_fixture_payload()
    record = payload["records"][0]
    record["title"] = "백엔드 개발자"
    record["description_text"] = body
    record["technology_mentions"] = [
        mention.model_dump(mode="json", by_alias=True)
        for mention in extract_technology_mentions(record["title"], body)
    ]
    batch = JobAnalysisInputBatch.model_validate(payload)
    before = batch.model_dump_json()
    results = classify_job_batch(batch, load_mapper()).records[0].technologies
    assert batch.model_dump_json() == before
    return {result.raw_technology: result for result in results}


@pytest.mark.parametrize(
    "evidence",
    [
        "Go 개발자 경력 3년 이상",
        "Go 언어를 활용한 서버 개발 경험",
        "Go 서버 개발 경험",
        "Go 개발 경험",
    ],
)
def test_collector_go_korean_context_maps_to_required(evidence: str) -> None:
    result = classify_collector_body(f"자격요건\n{evidence}")["Go"]
    assert result.tech_id == "go"
    assert result.match_status is MatchStatus.MATCHED
    assert result.requirement_class is RequirementClass.REQUIRED
    assert result.evidence_text == evidence


@pytest.mark.parametrize(
    "heading", ["담당업무", "주요 업무", "업무내용", "Responsibilities"]
)
@pytest.mark.parametrize("intermediate", ["", "신규 기술 검토\n"])
def test_duties_override_inherited_preferred_but_preserve_input(
    heading: str, intermediate: str
) -> None:
    body = f"우대사항\nPython 경험\n{heading}\n{intermediate}Docker 기반 서비스 개발"
    results = classify_collector_body(body)
    result = results["Docker"]
    assert results["Python"].requirement_class is RequirementClass.PREFERRED
    assert result.input_requirement_type == "PREFERRED"
    assert result.requirement_class is RequirementClass.REQUIRED
    assert result.parsed_section == heading
    if intermediate:
        assert result.evidence_section == "신규 기술 검토"
    assert result.evidence_text == "Docker 기반 서비스 개발"
    assert result.classification_reason == "responsibilities treated as required"
    assert result.parser_version == "job-requirement-rules/v2"


@pytest.mark.parametrize("input_type", ["MENTIONED", "REQUIRED", "PREFERRED"])
def test_source_duties_label_without_locatable_heading_is_required(
    input_type: str,
) -> None:
    payload = load_fixture_payload()
    record = payload["records"][0]
    record["description_text"] = "C# 실무 경험"
    mention = record["technology_mentions"][0]
    mention["evidence_section"] = "담당 업무"
    mention["requirement_type"] = input_type
    batch = JobAnalysisInputBatch.model_validate(payload)
    result = classify_job_batch(batch, load_mapper()).records[0].technologies[0]
    assert result.parsed_section is None
    assert result.requirement_class is RequirementClass.REQUIRED
    assert result.input_requirement_type == input_type


@pytest.mark.parametrize("heading", ["자격요건", "기술스택", "복리후생"])
def test_unrecognized_source_label_does_not_skip_parsed_section_conflict(
    heading: str,
) -> None:
    payload = load_fixture_payload()
    record = payload["records"][0]
    record["description_text"] = f"{heading}\n신규 기술 검토\nC# 실무 경험"
    mention = record["technology_mentions"][0]
    mention["evidence_section"] = "신규 기술 검토"
    mention["requirement_type"] = "PREFERRED"
    batch = JobAnalysisInputBatch.model_validate(payload)
    result = classify_job_batch(batch, load_mapper()).records[0].technologies[0]
    assert result.requirement_class is RequirementClass.REVIEW_REQUIRED
    assert result.parsed_section == heading
    assert result.evidence_section == "신규 기술 검토"


def test_preferred_subsection_ends_required_duties_policy() -> None:
    results = classify_collector_body(
        "담당업무\nDocker 기반 서비스 개발\n우대사항\nPython 경험"
    )
    assert results["Docker"].requirement_class is RequirementClass.REQUIRED
    assert results["Python"].requirement_class is RequirementClass.PREFERRED


def test_duties_do_not_confirm_unresolved_registry_mapping() -> None:
    payload = load_fixture_payload()
    record = payload["records"][3]
    record["description_text"] = "담당업무\nQuantumDB 경험"
    batch = JobAnalysisInputBatch.model_validate(payload)
    result = classify_job_batch(batch, load_mapper()).records[3].technologies[0]
    assert result.tech_id is None
    assert result.requirement_class is RequirementClass.REVIEW_REQUIRED
