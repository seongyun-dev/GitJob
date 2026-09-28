"""Deployment assets must publish the approved Registry and Rule Pack together."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_registry_import_script_rolls_out_common44_registry_and_rule_pack():
    script = (REPOSITORY_ROOT / "Infra/scripts/c-registry-import.sh").read_text(
        encoding="utf-8"
    )

    assert "technology_registry_20260911_4.json" in script
    assert "rule_pack_20260911_4.json" in script
    assert "PostgresRulePackStore" in script
    assert "registry_source_ref=" in script
    assert "C_RULE_PACK_SOURCE_REF" in script
    assert "activate_alias" in script
    assert "technology_registry_20260911_1.json" not in script


def test_worker_image_build_validates_common44_registry_and_rule_pack():
    dockerfile = (REPOSITORY_ROOT / "Infra/docker/worker/Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "technology_registry_20260911_4.json" in dockerfile
    assert "rule_pack_20260911_4.json" in dockerfile
    assert "technology_registry_20260911_1.json" not in dockerfile
