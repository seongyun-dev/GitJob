"""Real-extractor coverage gate for rules changed by the depth Rule Pack."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from depth_helpers import evaluate_depth_files

from analysis.rulepack import DEPTH_RULE_PACK_PATH, RULE_PACK_PATH

FIXTURE_ROOT = Path(__file__).with_name("fixtures") / "rule_pack_depth"


def _rules_by_id(path: Path) -> dict[str, dict[str, object]]:
    payload = json.loads(path.read_text("utf-8"))
    return {
        rule["rule_id"]: rule
        for profile in payload["technologies"]
        for rule in profile["rules"]
    }


BASE_RULES = _rules_by_id(RULE_PACK_PATH)
DEPTH_RULES = _rules_by_id(DEPTH_RULE_PACK_PATH)
CHANGED_RULE_IDS = frozenset(
    rule_id for rule_id, rule in DEPTH_RULES.items() if BASE_RULES.get(rule_id) != rule
)

FIXTURES = tuple(
    json.loads(path.read_text("utf-8")) for path in sorted(FIXTURE_ROOT.glob("*.json"))
)
CASES = tuple(
    (fixture["tech_id"], case) for fixture in FIXTURES for case in fixture["cases"]
)
DEPTH_CASES = tuple(
    pytest.param(tech_id, case, id=f"{tech_id}-{case['name']}")
    for tech_id, case in CASES
    if case["kind"] in {"positive", "near_miss"}
    and CHANGED_RULE_IDS
    & (set(case["expected_rule_ids"]) | set(case["absent_rule_ids"]))
)


def test_depth_pack_only_adds_or_changes_rules_from_the_published_base():
    assert set(BASE_RULES) <= set(DEPTH_RULES)
    assert CHANGED_RULE_IDS


def test_each_changed_rule_has_real_positive_and_dedicated_near_miss_cases():
    positive = {
        rule_id
        for _tech_id, case in CASES
        if case["kind"] == "positive"
        for rule_id in case["expected_rule_ids"]
    }
    near_miss = {
        rule_id
        for _tech_id, case in CASES
        if case["kind"] == "near_miss"
        for rule_id in case["absent_rule_ids"]
    }

    assert CHANGED_RULE_IDS == CHANGED_RULE_IDS & positive, (
        "changed rules without a real-file positive: "
        f"{sorted(CHANGED_RULE_IDS - positive)}"
    )
    assert CHANGED_RULE_IDS == CHANGED_RULE_IDS & near_miss, (
        "changed rules without a dedicated near miss: "
        f"{sorted(CHANGED_RULE_IDS - near_miss)}"
    )


@pytest.mark.parametrize("tech_id,case", DEPTH_CASES)
def test_changed_rule_cases_run_through_real_extractors(tech_id, case, tmp_path):
    judgement = evaluate_depth_files(tmp_path, case["files"])
    verdict = next(
        (item for item in judgement.verdicts if item.tech_id == tech_id), None
    )
    matched = set(verdict.matched_rule_ids) if verdict else set()
    expected = CHANGED_RULE_IDS & set(case["expected_rule_ids"])
    absent = CHANGED_RULE_IDS & set(case["absent_rule_ids"])

    assert expected <= matched
    assert not absent & matched
    if case["expected_level"] is not None:
        assert verdict is not None
        assert verdict.level == case["expected_level"]
