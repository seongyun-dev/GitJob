import json
from pathlib import Path

import pytest
from depth_helpers import evaluate_depth_files

ROOT = Path(__file__).parent / "fixtures/rule_pack_depth"
CASES = []
for technology in ("java", "python", "javascript", "typescript", "csharp"):
    path = ROOT / f"{technology}.json"
    if path.exists():
        for case in json.loads(path.read_text("utf-8"))["cases"]:
            CASES.append(
                pytest.param(technology, case, id=f"{technology}-{case['name']}")
            )


@pytest.mark.parametrize("tech,case", CASES)
def test_language_depth_is_backed_by_actual_structures_and_bound_calls(
    tech, case, tmp_path
):
    judgement = evaluate_depth_files(tmp_path, case["files"])
    levels = {v.tech_id: v.level for v in judgement.verdicts}
    assert levels.get(tech) == case["expected_level"]
    matched = {r for v in judgement.verdicts for r in v.matched_rule_ids}
    assert set(case["expected_rule_ids"]) <= matched
    assert not set(case["absent_rule_ids"]) & matched


def test_language_depth_fixture_inventory_is_not_empty():
    assert len(CASES) >= 35
