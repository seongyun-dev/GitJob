"""Every published executable rule needs real-file positive and near-miss evidence."""

import json

import pytest
from test_analysis_rule_pack_fixtures import FIXTURE_PATHS, _evaluate, _write_repository

from analysis.rulepack import RULE_PACK_PATH, load_rule_pack

CASES = [
    (path.stem, case)
    for path in FIXTURE_PATHS
    for case in json.loads(path.read_text(encoding="utf-8")).get("rule_cases", [])
]


@pytest.mark.parametrize(
    "tech_id,case", CASES, ids=[f"{tech}-{case['name']}" for tech, case in CASES]
)
def test_rule_case_uses_real_extraction(tech_id, case, tmp_path):
    _write_repository(tmp_path, case["files"])
    result = _evaluate(tmp_path)
    matched = {rule for verdict in result.verdicts for rule in verdict.matched_rule_ids}
    assert set(case["expected_rule_ids"]) <= matched
    assert not set(case.get("absent_rule_ids", ())) & matched
    assert all(rule.startswith(tech_id + ".") for rule in case["expected_rule_ids"])


def test_every_executable_rule_has_an_actual_file_positive_case():
    required = {
        rule.rule_id
        for profile in load_rule_pack(RULE_PACK_PATH).technologies
        for rule in profile.rules
    }
    declared = {rule for _, case in CASES for rule in case["expected_rule_ids"]}
    assert required == declared, f"uncovered rules: {sorted(required - declared)}"


def test_every_executable_rule_has_an_actual_file_negative_case():
    required = {
        rule.rule_id
        for profile in load_rule_pack(RULE_PACK_PATH).technologies
        for rule in profile.rules
    }
    declared = {rule for _, case in CASES for rule in case.get("absent_rule_ids", ())}
    assert required <= declared, (
        f"missing negative cases: {sorted(required - declared)}"
    )
