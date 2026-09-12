from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.configs import ConfigScanner, facts_from_configs
from analysis.judge import (
    Judge,
    facts_from_annotations,
    facts_from_calls,
    facts_from_dependencies,
    facts_from_imports,
    facts_from_sources,
)
from analysis.manifests import ManifestScanner
from analysis.parse import RepositoryParser
from analysis.rulepack import (
    RULE_PACK_PATH,
    load_rule_pack,
    mappings_from_registry_artifact,
)

FIXTURES = Path(__file__).parent / "fixtures" / "rule_pack_44"
REGISTRY = (
    RULE_PACK_PATH.parents[2]
    / "registry"
    / "data"
    / "technology_registry_20260911_2.json"
)


def _write_repository(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _evaluate(root: Path):
    report = RepositoryParser().parse_repository(root)
    dependencies = ManifestScanner().scan(root)
    configs = ConfigScanner().scan(root)
    facts = (
        facts_from_imports(report.occurrences)
        + facts_from_calls(report.calls)
        + facts_from_sources(report.sources)
        + facts_from_annotations(report.annotations)
        + facts_from_dependencies(dependencies.occurrences)
        + facts_from_configs(configs.occurrences)
    )
    pack = load_rule_pack(RULE_PACK_PATH)
    rules = pack.as_rule_set(mappings=mappings_from_registry_artifact(REGISTRY))
    return Judge(rules).judge(facts)


FIXTURE_PATHS = sorted(FIXTURES.glob("*.json"))


def test_fixture_inventory_is_one_independent_file_per_fixed_technology():
    pack = load_rule_pack(RULE_PACK_PATH)
    assert {path.stem for path in FIXTURE_PATHS} == set(pack.support)
    assert len(FIXTURE_PATHS) == 44


@pytest.mark.parametrize("fixture_path", FIXTURE_PATHS, ids=lambda path: path.stem)
def test_each_technology_runs_positive_negative_and_near_miss_through_real_extractors(
    fixture_path, tmp_path
):
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    tech_id = fixture["tech_id"]
    observed = {}
    for case in ("positive", "negative", "near_miss"):
        root = tmp_path / case
        _write_repository(root, fixture[case]["files"])
        judgement = _evaluate(root)
        observed[case] = {item.tech_id: item.level for item in judgement.verdicts}

    pack = load_rule_pack(RULE_PACK_PATH)
    ceiling = pack.support[tech_id].max_supported_level
    order = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
    assert tech_id in observed["positive"]
    assert order[observed["positive"][tech_id]] <= order[ceiling]
    assert tech_id not in observed["negative"]
    assert tech_id not in observed["near_miss"]


def test_torch_import_cannot_lend_identity_to_turtle_backward_in_the_same_file(
    tmp_path,
):
    _write_repository(
        tmp_path,
        {"main.py": "import torch\nimport turtle\nturtle.backward(10)\n"},
    )

    levels = {item.tech_id: item.level for item in _evaluate(tmp_path).verdicts}

    assert levels["pytorch"] == "L1"


def test_react_import_cannot_lend_identity_to_a_local_use_state_method(tmp_path):
    _write_repository(
        tmp_path,
        {
            "main.ts": (
                "import React from 'react';\n"
                "const local = { useState() { return 1; } };\n"
                "local.useState();\n"
            )
        },
    )

    levels = {item.tech_id: item.level for item in _evaluate(tmp_path).verdicts}

    assert levels["react"] == "L1"
