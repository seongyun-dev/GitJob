"""Structural evidence uses a new strict envelope; historical v2 stays readable."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_analysis_result_v2 import _judgement, _reports, _request

from analysis.__main__ import result_destination_from_env
from analysis.judge import EvidenceFact, Fact
from analysis.publish import completed_result
from analysis.results import RepositoryAnalysisResultV2


def depth_result():
    request = _request()
    request = request.model_copy(
        update={
            "payload": request.payload.model_copy(
                update={"registry_version": "registry-20260911.3"}
            )
        }
    )
    syntax = Fact(
        "SYNTAX_NODE",
        {
            "KIND": "ASYNC_FUNCTION_DECLARATION",
            "NAME": "main",
            "LANGUAGE": "python",
            "FILE_PATH": "main.py",
            "IS_TEST": "false",
        },
        "main.py",
        1,
    )
    original = _judgement()
    support = dict(original.technology_support["python"])
    support["required_fact_types"] = ("SYNTAX_NODE",)
    judgement = replace(
        original,
        rule_pack_version="rule-pack-20260911.3",
        evidence=(EvidenceFact("python.l1.source", "python", syntax),),
        technology_support={"python": support},
    )
    report, dependencies, configs = _reports()
    return completed_result(request, judgement, report, dependencies, configs=configs)


def test_structural_evidence_uses_v3_and_v2_rejects_it():
    result = depth_result()
    assert result.schema_version == "repository-analysis-result/v3"
    payload = result.model_dump(mode="json")
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "docs/data/contracts/repository-analysis-result-v3.schema.json"
    )
    Draft202012Validator(json.loads(schema_path.read_text("utf-8"))).validate(payload)
    with pytest.raises(ValidationError):
        RepositoryAnalysisResultV2.model_validate(payload)


def test_unchanged_v2_still_uses_the_v2_envelope():
    report, dependencies, configs = _reports()
    result = completed_result(
        _request(), _judgement(), report, dependencies, configs=configs
    )
    assert result.schema_version == "repository-analysis-result/v2"
    RepositoryAnalysisResultV2.model_validate(result.model_dump(mode="json"))


def test_runtime_v3_requires_explicit_distinct_topic():
    schema = "repository-analysis-result/v3"
    with pytest.raises(SystemExit, match="RESULTS_V3 is required"):
        result_destination_from_env({"ANALYSIS_RESULT_SCHEMA_VERSION": schema})
    env = {
        "ANALYSIS_RESULT_SCHEMA_VERSION": schema,
        "KAFKA_TOPIC_REPOSITORY_ANALYSIS_RESULTS_V3": "results.v3",
        "KAFKA_TOPIC_REPOSITORY_ANALYSIS_RESULTS_V2": "results.v2",
    }
    assert result_destination_from_env(env) == (schema, "results.v3")
    for other in (
        "KAFKA_TOPIC_REPOSITORY_ANALYSIS_RESULTS",
        "KAFKA_TOPIC_REPOSITORY_ANALYSIS_RESULTS_V2",
    ):
        with pytest.raises(SystemExit, match="must be distinct"):
            result_destination_from_env({**env, other: "results.v3"})
