from __future__ import annotations

from pathlib import Path

from analysis.judge import (
    Judge,
    facts_from_calls,
    facts_from_dependencies,
    facts_from_imports,
)
from analysis.manifests import ManifestScanner
from analysis.parse import RepositoryParser
from analysis.rulepack import (
    RULE_PACK_PATH,
    load_rule_pack,
    mappings_from_registry_artifact,
)

REGISTRY = (
    RULE_PACK_PATH.parents[2]
    / "registry"
    / "data"
    / "technology_registry_20260911_2.json"
)


def _evaluate(root: Path, relative: str, source: str):
    target = root / relative
    target.write_text(source, encoding="utf-8")
    report = RepositoryParser().parse_repository(root)
    pack = load_rule_pack(RULE_PACK_PATH)
    rules = pack.as_rule_set(mappings=mappings_from_registry_artifact(REGISTRY))
    judgement = Judge(rules).judge(
        facts_from_imports(report.occurrences) + facts_from_calls(report.calls)
    )
    levels = {verdict.tech_id: verdict.level for verdict in judgement.verdicts}
    return report, levels


def test_javascript_namespace_import_binds_api_receiver(tmp_path: Path) -> None:
    report, levels = _evaluate(
        tmp_path,
        "main.ts",
        "import * as React from 'react';\nReact.useState(0);\n",
    )

    assert report.occurrences[0].bindings == ("React",)
    assert levels["react"] == "L2"


def test_multiline_python_import_binds_api_function(tmp_path: Path) -> None:
    report, levels = _evaluate(
        tmp_path,
        "main.py",
        "from pandas import (\n    read_csv,\n)\nread_csv('data.csv')\n",
    )

    assert report.occurrences[0].bindings == ("read_csv",)
    assert levels["pandas"] == "L2"


def test_reassigned_import_alias_does_not_lend_identity_to_local_call(
    tmp_path: Path,
) -> None:
    _report, levels = _evaluate(
        tmp_path,
        "main.py",
        "import pandas as pd\n"
        "class Local:\n"
        "    def read_csv(self): return 1\n"
        "pd = Local()\n"
        "pd.read_csv()\n",
    )

    assert levels["pandas"] == "L1"


def test_parameter_shadow_does_not_lend_import_identity_to_local_call(
    tmp_path: Path,
) -> None:
    _report, levels = _evaluate(
        tmp_path,
        "main.py",
        "import pandas as pd\ndef load(pd):\n    return pd.read_csv('data.csv')\n",
    )

    assert levels["pandas"] == "L1"


def test_later_module_reassignment_does_not_hide_an_earlier_api_call(
    tmp_path: Path,
) -> None:
    _report, levels = _evaluate(
        tmp_path,
        "main.py",
        "import pandas as pd\npd.read_csv('data.csv')\npd = object()\n",
    )

    assert levels["pandas"] == "L2"


def test_attribute_assignment_does_not_shadow_imported_receiver(
    tmp_path: Path,
) -> None:
    _report, levels = _evaluate(
        tmp_path,
        "main.py",
        "import pandas as pd\npd.options.display = object()\npd.read_csv('data.csv')\n",
    )

    assert levels["pandas"] == "L2"


def test_fixture_manifest_dependency_does_not_become_production_evidence(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixtures" / "package.json"
    fixture.parent.mkdir()
    fixture.write_text('{"dependencies":{"react":"^19.0.0"}}', encoding="utf-8")
    dependencies = ManifestScanner().scan(tmp_path)
    facts = facts_from_dependencies(dependencies.occurrences)
    pack = load_rule_pack(RULE_PACK_PATH)
    rules = pack.as_rule_set(mappings=mappings_from_registry_artifact(REGISTRY))
    judgement = Judge(rules).judge(facts)

    assert facts[0].fields["IS_TEST"] == "true"
    assert "react" not in {verdict.tech_id for verdict in judgement.verdicts}
