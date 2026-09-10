"""The result contract, checked from the producing side.

The worker writes this event and B reads it. What matters here is that the two
cannot drift apart silently: every example below is validated against the
committed JSON Schema as well as the pydantic model, so a field added to one and
not the other fails a test rather than a deployment.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from analysis.results import (
    EVENT_TYPE,
    SCHEMA_VERSION,
    AnalysisStats,
    EvidenceItem,
    RepositoryAnalysisResult,
    RepositoryAnalysisResultPayload,
    TechnologyCandidate,
    TechnologyVerdict,
)

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "data"
    / "contracts"
    / "repository-analysis-result-v1.schema.json"
)
SHA = "818c4136ea971c21674525f9053de0d9c7ad8cfe"


def schema_validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def completed(**overrides) -> dict:
    payload = {
        "analysis_id": "an_1",
        "request_event_id": "ev_1",
        "registry_version": "registry-20260908.1",
        "commit_sha": SHA,
        "status": "COMPLETED",
        "technologies": [
            {
                "tech_id": "spring-boot",
                "level": "L3",
                "matched_rule_ids": [
                    "spring-boot.l1.java-import",
                    "spring-boot.l3.actuator",
                ],
            }
        ],
        "evidence": [
            {
                "rule_id": "spring-boot.l1.java-import",
                "fact_type": "IMPORT",
                "file_path": "src/main/java/App.java",
                "start_line": 3,
                "end_line": 3,
                "fact_payload": {
                    "MODULE": "org.springframework.boot.SpringApplication",
                    "LANGUAGE": "java",
                },
            }
        ],
        "candidates": [
            {
                "ecosystem": "MAVEN",
                "coordinate": "org.postgresql:postgresql",
                "scope": "runtimeOnly",
                "occurrence_count": 1,
            }
        ],
        "stats": {"files_parsed": 50, "import_count": 471},
    }
    payload.update(overrides)
    return {
        "event_id": "ev_result_1",
        "schema_version": SCHEMA_VERSION,
        "event_type": EVENT_TYPE,
        "occurred_at": "2026-09-10T01:02:03Z",
        "trace_id": "tr_1",
        "payload": payload,
    }


def test_a_completed_result_satisfies_both_the_model_and_the_schema():
    body = completed()
    schema_validator().validate(body)

    event = RepositoryAnalysisResult.model_validate(body)
    assert event.payload.technologies[0].level == "L3"
    assert event.payload.evidence[0].start_line == 3
    assert event.payload.candidates[0].coordinate == "org.postgresql:postgresql"


def test_the_model_serializes_into_something_the_schema_still_accepts():
    # The round trip is the part that drifts: a model field renamed on this side
    # produces a message B's schema rejects, and only in production.
    event = RepositoryAnalysisResult.model_validate(completed())
    emitted = json.loads(event.model_dump_json())
    schema_validator().validate(emitted)


def test_failure_travels_on_this_topic_and_carries_its_code():
    # The DLQ is for operators. Without this, analysis_job stays QUEUED forever
    # and the user never sees that their deleted repository failed.
    body = completed(
        status="FAILED",
        error_code="REPOSITORY_NOT_FOUND",
        error_detail="git fetch could not find the repository or commit",
        technologies=[],
        evidence=[],
        candidates=[],
    )
    schema_validator().validate(body)

    event = RepositoryAnalysisResult.model_validate(body)
    assert event.payload.status == "FAILED"
    assert event.payload.error_code == "REPOSITORY_NOT_FOUND"


def test_a_failure_without_a_code_is_refused_by_both_sides():
    body = completed(status="FAILED", technologies=[], evidence=[], candidates=[])
    assert not schema_validator().is_valid(body)
    with pytest.raises(ValidationError):
        RepositoryAnalysisResult.model_validate(body)


def test_a_failure_carrying_findings_is_refused():
    # B would write evidence rows for an analysis it is about to mark failed.
    with pytest.raises(ValidationError, match="must not carry findings"):
        RepositoryAnalysisResult.model_validate(
            completed(status="FAILED", error_code="CLONE_TIMEOUT")
        )


def test_a_success_carrying_an_error_code_is_refused():
    with pytest.raises(ValidationError, match="belongs to a FAILED result"):
        RepositoryAnalysisResult.model_validate(completed(error_code="CLONE_TIMEOUT"))


def test_nothing_matched_is_a_valid_success():
    # Distinguishable from failure only because status says so. This is exactly
    # the case a wrong registry_version would silently imitate.
    body = completed(technologies=[], evidence=[], candidates=[])
    schema_validator().validate(body)
    assert RepositoryAnalysisResult.model_validate(body).payload.status == "COMPLETED"


def test_the_envelope_refuses_a_version_it_does_not_implement():
    with pytest.raises(ValidationError):
        RepositoryAnalysisResult.model_validate(
            completed() | {"schema_version": "repository-analysis-result/v2"}
        )


def test_no_user_identity_can_be_smuggled_into_the_payload():
    # The topic outlives the request. analysis_id is enough for B to resolve the
    # owner, so identity has no reason to be here.
    body = completed()
    body["payload"]["user_id"] = 1
    assert not schema_validator().is_valid(body)
    with pytest.raises(ValidationError):
        RepositoryAnalysisResult.model_validate(body)


def test_a_verdict_must_name_the_rules_behind_it():
    with pytest.raises(ValidationError):
        TechnologyVerdict(tech_id="redis", level="L1", matched_rule_ids=())


def test_an_inverted_line_range_is_refused():
    with pytest.raises(ValidationError, match="must not precede"):
        EvidenceItem(
            rule_id="r",
            fact_type="IMPORT",
            file_path="a.java",
            start_line=10,
            end_line=9,
            fact_payload={},
        )


def test_a_candidate_keeps_its_scope_so_test_only_use_stays_distinguishable():
    # Re-deriving scope later would mean cloning the repository again.
    candidate = TechnologyCandidate(
        ecosystem="MAVEN",
        coordinate="org.testcontainers:testcontainers",
        scope="testImplementation",
        occurrence_count=2,
    )
    assert candidate.scope == "testImplementation"


def test_stats_default_to_zero_rather_than_missing():
    # An absent count and a count of zero read the same in a dashboard, so the
    # model does not leave the difference to the producer.
    assert AnalysisStats().files_parsed == 0


def test_the_payload_rejects_a_short_commit_sha():
    with pytest.raises(ValidationError, match="40 lowercase hex"):
        RepositoryAnalysisResultPayload(
            analysis_id="an_1",
            request_event_id="ev_1",
            registry_version="registry-20260908.1",
            commit_sha="818c4136ea97",
            status="COMPLETED",
        )
