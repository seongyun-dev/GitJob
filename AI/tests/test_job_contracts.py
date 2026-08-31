import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from job.contracts import (
    BodyStatus,
    JobAnalysisInputBatch,
    adapt_job_analysis_input,
    find_semantic_duplicate_groups,
    map_source_technology_id,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "job" / "fixtures"
EXPECTED_FIXTURE_CASE_IDS = {
    "alias-csharp-required",
    "alias-nodejs-preferred",
    "alias-nextjs-mentioned",
    "alias-vuejs-mentioned",
    "pass-through-python-mentioned",
    "ambiguous-c-title",
    "ambiguous-r-title",
    "ambiguous-go-title",
    "unknown-quantumdb",
    "duplicate-cpp-required",
    "alias-dotnet-mentioned",
    "alias-dotnet-maui-mentioned",
}
EXPECTED_INVALID_CASE_NAMES = {
    "unsupported_schema_version",
    "missing_pipeline_run_id",
    "numeric_source_posting_id",
    "text_status_without_description",
    "unsupported_requirement_type",
    "unsafe_source_technology_id",
    "internal_technology_id_field_name",
    "numeric_collected_at",
}


def valid_payload() -> dict[str, object]:
    return {
        "schema_version": "job-analysis-input/v1",
        "dataset_snapshot_id": "fixture-job-snapshot-20260831",
        "pipeline_run_id": "fixture-pipeline-run-001",
        "collector_version": "fixture-a-collector-v1",
        "records": [
            {
                "source_record_id": "jobkorea:fixture-1001",
                "canonical_job_id": "fixture-job-001",
                "source_site": "JOBKOREA",
                "source_posting_id": "fixture-1001",
                "source_url": "https://example.invalid/jobs/fixture-1001",
                "company_name": "Fixture Labs",
                "title": "C# 백엔드 개발자",
                "raw_job_category": "백엔드 개발",
                "career_level": "경력 3년 이상",
                "region": "서울",
                "description_text": "자격요건: C# 실무 경험",
                "body_status": "TEXT_AVAILABLE",
                "posting_status": "ACTIVE",
                "collected_at": "2026-08-31T00:00:00Z",
                "content_hash": "a" * 64,
                "technology_mentions": [
                    {
                        "raw_technology": "C#",
                        "technology_id": "c#",
                        "requirement_type": "REQUIRED",
                        "source_surface": "BODY",
                        "evidence_section": "자격요건",
                        "evidence_text": "C# 실무 경험",
                        "extraction_method": "FIXTURE_RULE",
                    }
                ],
            }
        ],
    }


def test_valid_batch_is_strict_and_preserves_source_fields() -> None:
    batch = JobAnalysisInputBatch.model_validate(valid_payload())

    record = batch.records[0]
    mention = record.technology_mentions[0]
    assert record.source_posting_id == "fixture-1001"
    assert mention.source_technology_id == "c#"
    assert mention.raw_technology == "C#"
    assert mention.evidence_text == "C# 실무 경험"


def test_text_available_body_status_accepts_general_posting_body() -> None:
    payload = valid_payload()
    payload["records"][0]["body_status"] = "TEXT_AVAILABLE"  # type: ignore[index]

    batch = JobAnalysisInputBatch.model_validate(payload)

    assert batch.records[0].body_status is BodyStatus.TEXT_AVAILABLE


def test_legacy_text_body_status_is_rejected() -> None:
    payload = valid_payload()
    payload["records"][0]["body_status"] = "TEXT"  # type: ignore[index]

    with pytest.raises(ValidationError, match="TEXT_AVAILABLE"):
        JobAnalysisInputBatch.model_validate(payload)


@pytest.mark.parametrize("timestamp", [0, 0.0, "0", True])
def test_collected_at_rejects_epoch_like_values(timestamp: object) -> None:
    payload = valid_payload()
    payload["records"][0]["collected_at"] = timestamp  # type: ignore[index]

    with pytest.raises(ValidationError, match="ISO 8601 date-time string"):
        JobAnalysisInputBatch.model_validate(payload)


def test_json_schema_exposes_boundary_alias_as_nullable_string() -> None:
    schema = JobAnalysisInputBatch.model_json_schema(by_alias=True)
    mention_schema = schema["$defs"]["TechnologyMentionInput"]

    assert "technology_id" in mention_schema["properties"]
    assert "source_technology_id" not in mention_schema["properties"]
    assert "technology_id" in mention_schema["required"]
    assert "registry_version" not in schema["properties"]


def test_boundary_rejects_internal_technology_id_field_name() -> None:
    payload = valid_payload()
    mention = payload["records"][0]["technology_mentions"][0]  # type: ignore[index]
    mention["source_technology_id"] = mention.pop("technology_id")  # type: ignore[union-attr]

    with pytest.raises(ValidationError, match="technology_id"):
        JobAnalysisInputBatch.model_validate(payload)


def test_default_serialization_uses_boundary_technology_id_alias() -> None:
    batch = JobAnalysisInputBatch.model_validate(valid_payload())

    serialized_mention = batch.model_dump()["records"][0]["technology_mentions"][0]

    assert serialized_mention["technology_id"] == "c#"
    assert "source_technology_id" not in serialized_mention


@pytest.mark.parametrize(
    ("source_technology_id", "expected_tech_id"),
    [
        ("c#", "csharp"),
        ("c++", "cpp"),
        (".net", "dotnet"),
        (".net-maui", "dotnet-maui"),
        ("node.js", "nodejs"),
        ("next.js", "nextjs"),
        ("vue.js", "vuejs"),
        ("spring-boot", "spring-boot"),
    ],
)
def test_source_technology_id_has_explicit_safe_mapping(
    source_technology_id: str,
    expected_tech_id: str,
) -> None:
    assert map_source_technology_id(source_technology_id) == expected_tech_id


def test_unmapped_unsafe_technology_id_fails_explicitly() -> None:
    with pytest.raises(ValueError, match="unsafe source technology_id"):
        map_source_technology_id("React.js")


def test_unmapped_unsafe_technology_id_fails_at_input_boundary() -> None:
    payload = valid_payload()
    mention = payload["records"][0]["technology_mentions"][0]  # type: ignore[index]
    mention["technology_id"] = "React.js"  # type: ignore[index]

    with pytest.raises(ValidationError, match="technology_id"):
        JobAnalysisInputBatch.model_validate(payload)


def test_unknown_mention_is_not_dropped_by_boundary_adapter() -> None:
    payload = valid_payload()
    mention = payload["records"][0]["technology_mentions"][0]  # type: ignore[index]
    mention.update(  # type: ignore[union-attr]
        {
            "raw_technology": "QuantumDB",
            "technology_id": None,
            "requirement_type": "MENTIONED",
            "evidence_text": "QuantumDB 경험",
        }
    )

    internal = adapt_job_analysis_input(JobAnalysisInputBatch.model_validate(payload))

    assert len(internal.records[0].technology_mentions) == 1
    internal_mention = internal.records[0].technology_mentions[0]
    assert internal_mention.tech_id is None
    assert internal_mention.source_technology_id is None
    assert internal_mention.raw_technology == "QuantumDB"


def test_semantic_duplicate_candidates_are_reported_without_removal() -> None:
    payload = valid_payload()
    duplicate = deepcopy(payload["records"][0])  # type: ignore[index]
    duplicate["source_record_id"] = "wanted:fixture-2001"
    duplicate["source_site"] = "WANTED"
    duplicate["source_posting_id"] = "fixture-2001"
    duplicate["source_url"] = "https://example.invalid/jobs/fixture-2001"
    payload["records"].append(duplicate)  # type: ignore[union-attr]
    batch = JobAnalysisInputBatch.model_validate(payload)

    duplicate_groups = find_semantic_duplicate_groups(batch.records)

    assert len(batch.records) == 2
    assert duplicate_groups == {
        "fixture-job-001": (
            "jobkorea:fixture-1001",
            "wanted:fixture-2001",
        )
    }


def test_repeated_delivery_is_not_a_semantic_duplicate_group() -> None:
    payload = valid_payload()
    payload["records"].append(deepcopy(payload["records"][0]))  # type: ignore[union-attr,index]
    batch = JobAnalysisInputBatch.model_validate(payload)

    assert find_semantic_duplicate_groups(batch.records) == {}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"schema_version": "job-analysis-input/v2"}),
        lambda payload: payload.pop("pipeline_run_id"),
        lambda payload: payload["records"][0].update(  # type: ignore[index]
            {"source_posting_id": 1001}
        ),
        lambda payload: payload["records"][0].update(  # type: ignore[index]
            {"description_text": None}
        ),
        lambda payload: payload["records"][0]["technology_mentions"][  # type: ignore[index]
            0
        ].update({"requirement_type": "MANDATORY"}),
    ],
)
def test_invalid_contract_payloads_fail_deterministically(mutate) -> None:
    payload = valid_payload()
    mutate(payload)

    with pytest.raises(ValidationError):
        JobAnalysisInputBatch.model_validate(payload)


def test_committed_valid_fixture_matches_expected_cases() -> None:
    batch = JobAnalysisInputBatch.model_validate_json(
        (FIXTURE_ROOT / "job_analysis_input_v1.json").read_text(encoding="utf-8")
    )
    expected = json.loads(
        (FIXTURE_ROOT / "job_analysis_expected_v1.json").read_text(encoding="utf-8")
    )
    internal = adapt_job_analysis_input(batch)
    actual_mentions = {
        (record.source_record_id, mention.raw_technology): mention
        for record in internal.records
        for mention in record.technology_mentions
    }

    assert expected["expected_versions"] == {
        "registry_version": "fixture-registry-v1",
        "requirement_rule_version": "fixture-requirement-rules-v1",
    }
    assert {case["case_id"] for case in expected["cases"]} == (
        EXPECTED_FIXTURE_CASE_IDS
    )
    assert len(actual_mentions) == len(expected["cases"])
    for case in expected["cases"]:
        key = (case["source_record_id"], case["raw_technology"])
        actual = actual_mentions[key]
        assert actual.tech_id == case["expected_tech_id"]
        assert actual.requirement_type == case["input_requirement_type"]

    assert {case["expected_match_status"] for case in expected["cases"]} >= {
        "MATCHED",
        "AMBIGUOUS",
        "UNKNOWN",
    }
    assert {case["expected_requirement_class"] for case in expected["cases"]} >= {
        "REQUIRED",
        "PREFERRED",
        "SKILL",
        "REVIEW_REQUIRED",
    }
    assert {record.body_status for record in batch.records} == set(BodyStatus)
    assert find_semantic_duplicate_groups(batch.records) == {
        "fixture-job-001": (
            "jobkorea:fixture-1001",
            "wanted:fixture-2001",
        )
    }


def test_committed_invalid_fixture_cases_are_all_rejected() -> None:
    invalid_cases = json.loads(
        (FIXTURE_ROOT / "invalid_job_analysis_input_v1.json").read_text(
            encoding="utf-8"
        )
    )["cases"]

    assert {case["name"] for case in invalid_cases} == (EXPECTED_INVALID_CASE_NAMES)
    for case in invalid_cases:
        with pytest.raises(
            ValidationError,
            match=case["expected_error"],
        ):
            JobAnalysisInputBatch.model_validate(case["payload"])
