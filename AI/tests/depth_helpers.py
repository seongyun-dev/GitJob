"""Real-file harness shared by depth Rule Pack acceptance fixtures."""

import hashlib
import json
from pathlib import Path

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
    DEPTH_RULE_PACK_PATH,
    mappings_from_registry_artifact,
    parse_rule_pack,
)

AI_ROOT = Path(__file__).resolve().parents[1]
DEPTH_REGISTRY = AI_ROOT / "registry/data/technology_registry_20260911_3.json"


def depth_pack(profile=None):
    payload = json.loads(DEPTH_RULE_PACK_PATH.read_text("utf-8"))
    if profile is not None:
        payload["technologies"] = [
            profile if row["tech_id"] == profile["tech_id"] else row
            for row in payload["technologies"]
        ]
        content = {
            key: value for key, value in payload.items() if key != "content_sha256"
        }
        payload["content_sha256"] = hashlib.sha256(
            json.dumps(
                content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    return parse_rule_pack(payload)


def evaluate_depth_files(root, files, *, profile=None):
    from analysis.judge import facts_from_syntax

    root = Path(root)
    for relative, content in files.items():
        path = root / relative
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("fixture path escapes root")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, "utf-8")
    report = RepositoryParser().parse_repository(root)
    dependencies = ManifestScanner().scan(root)
    configs = ConfigScanner().scan(root)
    facts = (
        facts_from_imports(report.occurrences)
        + facts_from_calls(report.calls)
        + facts_from_sources(report.sources)
        + facts_from_annotations(report.annotations)
        + facts_from_syntax(report.syntax)
        + facts_from_dependencies(dependencies.occurrences)
        + facts_from_configs(configs.occurrences)
    )
    pack = depth_pack(profile)
    return Judge(
        pack.as_rule_set(mappings=mappings_from_registry_artifact(DEPTH_REGISTRY))
    ).judge(facts)
