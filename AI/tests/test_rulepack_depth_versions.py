"""A deeper pack must coexist with the previously validated immutable pack."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from analysis.rulepack import InvalidRulePack, load_rule_pack, parse_rule_pack
from registry.contracts import load_registry

AI_ROOT = Path(__file__).resolve().parents[1]
OLD_PACK = AI_ROOT / "analysis/data/rule_pack_20260911_2.json"
NEW_PACK = AI_ROOT / "analysis/data/rule_pack_20260911_3.json"
NEW_REGISTRY = AI_ROOT / "registry/data/technology_registry_20260911_3.json"


def test_depth_pack_keeps_fixed_ids_and_old_pack_immutable():
    old = load_rule_pack(OLD_PACK)
    assert (
        old.content_sha256
        == "bea078f6674249c843771e9a67ad9134d77fe89da9ff6141b120c47decb65b4f"
    )
    registry = load_registry(NEW_REGISTRY, repository_root=AI_ROOT.parent)
    new = load_rule_pack(NEW_PACK, registry=registry)
    assert new.rule_pack_version == "rule-pack-20260911.3"
    assert set(new.support) == set(old.support)
    assert len(new.support) == 44


def test_depth_pack_rejects_cross_version_registry_even_with_valid_hash():
    payload = json.loads(NEW_PACK.read_text("utf-8"))
    payload["registry_version"] = "registry-20260911.2"
    content = {k: v for k, v in payload.items() if k != "content_sha256"}
    payload["content_sha256"] = hashlib.sha256(
        json.dumps(
            content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    with pytest.raises(InvalidRulePack, match="version"):
        parse_rule_pack(copy.deepcopy(payload))
