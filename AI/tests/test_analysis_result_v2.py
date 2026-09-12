from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from analysis.__main__ import result_destination_from_env
from analysis.configs import ConfigOccurrence, ConfigReport
from analysis.contracts import RepositoryAnalysisRequest
from analysis.judge import Candidate, EvidenceFact, Fact, Judgement, Verdict
from analysis.manifests import DependencyReport
from analysis.parse import ParseReport, SourceFileOccurrence
from analysis.publish import ResultPublisher, completed_result, failed_result
from analysis.results import (
    SCHEMA_VERSION,
    SCHEMA_VERSION_V2,
    EvidenceItem,
    RepositoryAnalysisResultV2,
)

SHA = "818c4136ea971c21674525f9053de0d9c7ad8cfe"
SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "data"
    / "contracts"
    / "repository-analysis-result-v2.schema.json"
)


def _request() -> RepositoryAnalysisRequest:
    return RepositoryAnalysisRequest.model_validate(
        {
            "event_id": "ev_common44",
            "schema_version": "repository-analysis-request/v1",
            "event_type": "repository.analysis.requested",
            "occurred_at": "2026-09-12T01:02:03Z",
            "trace_id": "tr_common44",
            "payload": {
                "analysis_id": "an_common44",
                "analysis_repository_id": "ar_common44",
                "github_repository_id": 1,
                "repository_full_name": "octocat/gitjob",
                "branch_name": "main",
                "commit_sha": SHA,
                "analysis_mode": "SNAPSHOT",
                "registry_version": "registry-20260911.2",
            },
        }
    )


def _judgement(*, candidate_ecosystem: str = "GO") -> Judgement:
    source = Fact(
        "SOURCE_FILE",
        {
            "FILE_PATH": "src/main.py",
            "LANGUAGE": "python",
            "EXTENSION": ".py",
            "SLOC": "1",
            "IS_TEST": "false",
        },
        "src/main.py",
        1,
    )
    return Judgement(
        verdicts=(Verdict("python", "L1", ("python.l1.source",)),),
        evidence=(EvidenceFact("python.l1.source", "python", source),),
        candidates=(
            Candidate(candidate_ecosystem, "example.invalid/module", "require", 1),
        ),
        rule_pack_version="rule-pack-20260911.2",
        rule_pack_content_sha256="a" * 64,
        technology_support={
            "python": {
                "evaluation_scope": "REPOSITORY",
                "required_fact_types": ("SOURCE_FILE",),
                "max_supported_level": "L1",
                "coverage": "PARTIAL",
                "limitations": ("Parser coverage is partial.",),
            }
        },
    )


def _reports() -> tuple[ParseReport, DependencyReport, ConfigReport]:
    return (
        ParseReport(
            occurrences=(),
            files_parsed=1,
            files_skipped=1,
            bytes_parsed=20,
            sources=(SourceFileOccurrence("python", ".py", 1, False, "src/main.py"),),
            skipped_reasons={"too_large": 1},
        ),
        DependencyReport((), 1, {"manifest_error": 1}),
        ConfigReport(
            (ConfigOccurrence("YAML", "kind", "Service", "app.yaml", 1),),
            1,
            {"config_error": 1},
        ),
    )


def test_common44_result_is_explicit_v2_and_schema_valid():
    report, dependencies, configs = _reports()
    result = completed_result(
        _request(), _judgement(), report, dependencies, configs=configs
    )

    assert isinstance(result, RepositoryAnalysisResultV2)
    assert result.schema_version == SCHEMA_VERSION_V2
    assert result.payload.evidence[0].fact_type == "SOURCE_FILE"
    assert result.payload.candidates[0].ecosystem == "GO"
    assert result.payload.stats.source_file_count == 1
    assert result.payload.stats.config_count == 1
    assert result.payload.stats.skipped_reasons == {
        "source:too_large": 1,
        "manifest:manifest_error": 1,
        "config:config_error": 1,
    }
    Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))).validate(
        json.loads(result.model_dump_json())
    )


def test_v1_refuses_source_file_evidence_and_filters_new_manifest_candidates():
    with pytest.raises(ValidationError):
        EvidenceItem(
            rule_id="python.l1.source",
            fact_type="SOURCE_FILE",
            file_path="src/main.py",
            start_line=1,
            end_line=1,
            fact_payload={},
        )

    report, dependencies, _configs = _reports()
    legacy = _judgement()
    legacy = Judgement(
        verdicts=(),
        evidence=(),
        candidates=legacy.candidates,
    )
    result = completed_result(_request(), legacy, report, dependencies)
    assert result.schema_version == SCHEMA_VERSION
    assert result.payload.candidates == ()


def test_common44_cannot_be_silently_downgraded_to_v1():
    report, dependencies, configs = _reports()
    with pytest.raises(ValueError, match="require repository-analysis-result/v2"):
        completed_result(
            _request(),
            _judgement(),
            report,
            dependencies,
            configs=configs,
            schema_version=SCHEMA_VERSION,
        )


def test_no_supported_fact_emits_no_negative_level_but_keeps_partial_ceiling():
    report, dependencies, configs = _reports()
    original = _judgement()
    empty = Judgement(
        verdicts=(),
        evidence=(),
        candidates=(),
        rule_pack_version=original.rule_pack_version,
        rule_pack_content_sha256=original.rule_pack_content_sha256,
        technology_support=original.technology_support,
    )

    result = completed_result(_request(), empty, report, dependencies, configs=configs)

    assert result.payload.technologies == ()
    assert result.payload.technology_support[0].coverage == "PARTIAL"
    assert result.payload.technology_support[0].max_supported_level == "L1"


def test_v2_failure_and_publisher_use_the_negotiated_topic():
    class Transport:
        def __init__(self):
            self.sent = []

        def send(self, topic, *, key, value):
            self.sent.append((topic, key, value))

    result = failed_result(_request(), "CLONE_FAILED", schema_version=SCHEMA_VERSION_V2)
    transport = Transport()
    publisher = ResultPublisher(
        transport, "results.v2", schema_version=SCHEMA_VERSION_V2
    )
    publisher.publish(result)
    assert json.loads(transport.sent[0][2])["schema_version"] == SCHEMA_VERSION_V2

    with pytest.raises(ValueError, match="cannot be published"):
        ResultPublisher(transport, "results.v1", schema_version=SCHEMA_VERSION).publish(
            result
        )


def test_runtime_v2_opt_in_requires_a_distinct_topic():
    assert result_destination_from_env({}) == (
        SCHEMA_VERSION,
        "gitjob.repository-analysis.results.v1",
    )
    assert result_destination_from_env(
        {
            "ANALYSIS_RESULT_SCHEMA_VERSION": SCHEMA_VERSION_V2,
            "KAFKA_TOPIC_REPOSITORY_ANALYSIS_RESULTS_V2": "gitjob.repository-analysis.results.v2",
        }
    ) == (SCHEMA_VERSION_V2, "gitjob.repository-analysis.results.v2")
    with pytest.raises(SystemExit, match="RESULTS_V2 is required"):
        result_destination_from_env(
            {"ANALYSIS_RESULT_SCHEMA_VERSION": SCHEMA_VERSION_V2}
        )
