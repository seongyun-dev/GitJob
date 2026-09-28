"""Acceptance coverage for application and data depth profiles.

The fixtures are executable repository snippets.  Every new rule must prove a
positive and a one-condition-short near miss through the real scanners.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from depth_helpers import evaluate_depth_files

from analysis.rulepack import DEPTH_RULE_PACK_PATH, load_rule_pack

FIXTURE_ROOT = Path(__file__).with_name("fixtures") / "rule_pack_depth"
APP_DATA_TECH_IDS = (
    "spring-framework",
    "spring-boot",
    "jpa",
    "mybatis",
    "dotnet",
    "nodejs",
    "nestjs",
    "django",
    "fastapi",
    "react",
    "nextjs",
    "vuejs",
    "unity",
    "numpy",
    "pandas",
    "scikit-learn",
    "pytorch",
    "tensorflow",
    "apache-spark",
    "hadoop",
    "apache-kafka",
    "mysql",
    "postgresql",
    "mongodb",
    "redis",
)
EXPECTED_NEW_RULES = {
    "spring-framework.l2.bean-configuration",
    "spring-boot.l3.observability",
    "jpa.l2.query",
    "jpa.l3.transactional-locking",
    "mybatis.l2.session-dynamic",
    "dotnet.l2.host-di",
    "dotnet.l3.background-worker-lifecycle",
    "nodejs.l3.worker-stream-pipeline",
    "nestjs.l3.interceptor-error-lifecycle",
    "fastapi.l3.composed-application",
    "react.l3.concurrent-rendering",
    "nextjs.l3.middleware-routing",
    "unity.l2.lifecycle-component",
    "unity.l3.parallel-job",
    "scikit-learn.l3.tuned-pipeline",
    "pytorch.l3.distributed-checkpoint",
    "tensorflow.l3.strategy-training",
    "apache-spark.l2.dataframe",
    "apache-spark.l3.partitioned-caching",
    "hadoop.l3.filesystem-job",
    "apache-kafka.l3.transactional-consumer",
    "mysql.l2.driver-api",
    "postgresql.l2.driver-api",
    "mongodb.l3.transaction-stream",
}


def _fixtures():
    return [
        json.loads((FIXTURE_ROOT / f"{tech_id}.json").read_text("utf-8"))
        for tech_id in APP_DATA_TECH_IDS
    ]


def test_all_owned_depth_profiles_and_fixtures_are_published():
    pack = load_rule_pack(DEPTH_RULE_PACK_PATH)
    published = {
        rule.rule_id
        for tech_id in APP_DATA_TECH_IDS
        for rule in pack.support[tech_id].rules
    }

    assert EXPECTED_NEW_RULES <= published
    assert {fixture["tech_id"] for fixture in _fixtures()} == set(APP_DATA_TECH_IDS)


def test_every_new_app_data_rule_has_positive_and_near_miss_evidence():
    cases = [case for fixture in _fixtures() for case in fixture["cases"]]
    positive = {
        rule_id
        for case in cases
        if case["kind"] == "positive"
        for rule_id in case["expected_rule_ids"]
    }
    near_miss = {
        rule_id
        for case in cases
        if case["kind"] == "near_miss"
        for rule_id in case["absent_rule_ids"]
    }

    assert EXPECTED_NEW_RULES <= positive
    assert EXPECTED_NEW_RULES <= near_miss


def test_adversarial_cases_cover_identity_and_authorship_boundaries():
    names = {case["name"] for fixture in _fixtures() for case in fixture["cases"]}

    assert {
        "unrelated-object-methods",
        "shadowed-import-bindings",
        "comments-and-strings",
        "test-only-composition",
        "vendored-composition",
        "generated-library-source",
        "signals-split-across-classes",
        "signals-split-across-functions",
    } <= names


@pytest.mark.parametrize("tech_id", APP_DATA_TECH_IDS)
def test_app_data_depth_cases_use_real_extraction(tech_id, tmp_path):
    fixture = json.loads((FIXTURE_ROOT / f"{tech_id}.json").read_text("utf-8"))
    for index, case in enumerate(fixture["cases"]):
        result = evaluate_depth_files(tmp_path / str(index), case["files"])
        verdict = next((v for v in result.verdicts if v.tech_id == tech_id), None)
        matched = set(verdict.matched_rule_ids) if verdict else set()
        if case["expected_level"] is None:
            assert verdict is None or verdict.level != "L3"
        else:
            assert verdict is not None
            assert verdict.level == case["expected_level"]
        assert set(case["expected_rule_ids"]) <= matched
        assert not set(case["absent_rule_ids"]) & matched


def test_l3_rules_are_composite_and_source_bound():
    pack = load_rule_pack(DEPTH_RULE_PACK_PATH)
    for tech_id in APP_DATA_TECH_IDS:
        for rule in pack.support[tech_id].rules:
            if rule.rule_id not in EXPECTED_NEW_RULES or rule.rule_type != "L3":
                continue
            assert rule.binding_fields == ("FILE_PATH", "COMPONENT")
            assert all(len(group) >= 3 for group in rule.groups)
            assert all(
                all(clause.role == "REQUIRED" for clause in group)
                for group in rule.groups
            )
