from __future__ import annotations

import hashlib
import json

import pytest

from analysis.judge import Fact, Judge
from analysis.rulepack import (
    RULE_PACK_PATH,
    InvalidRulePack,
    load_rule_pack,
    mappings_from_registry_artifact,
    parse_rule_pack,
)
from analysis.rules import Clause, Mapping, Predicate, Rule, RuleSet

EXPECTED_TECH_IDS = {
    "c",
    "cpp",
    "csharp",
    "go",
    "java",
    "kotlin",
    "python",
    "javascript",
    "typescript",
    "php",
    "sql",
    "html",
    "css",
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
    "docker",
    "kubernetes",
    "aws",
    "azure",
    "gcp",
    "jenkins",
}


def _rehash(payload):
    content = {key: value for key, value in payload.items() if key != "content_sha256"}
    payload["content_sha256"] = hashlib.sha256(
        json.dumps(
            content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    return payload


def test_rule_pack_is_exactly_the_fixed_44_with_explicit_support_metadata():
    pack = load_rule_pack(RULE_PACK_PATH)

    assert pack.registry_version == "registry-20260911.2"
    assert pack.rule_pack_version == "rule-pack-20260911.2"
    assert set(pack.support) == EXPECTED_TECH_IDS
    assert len(pack.support) == 44
    assert all(
        profile.evaluation_scope == "REPOSITORY" for profile in pack.support.values()
    )
    assert all(profile.required_fact_types for profile in pack.support.values())
    assert all(
        profile.max_supported_level in {"L0", "L1", "L2", "L3"}
        for profile in pack.support.values()
    )
    assert all(
        profile.coverage in {"SUPPORTED", "PARTIAL", "UNSUPPORTED"}
        for profile in pack.support.values()
    )


def test_rule_pack_content_hash_is_verified(tmp_path):
    payload = json.loads(RULE_PACK_PATH.read_text(encoding="utf-8"))
    payload["technologies"][0]["max_supported_level"] = "L3"
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(InvalidRulePack, match="content_sha256"):
        load_rule_pack(tampered)


def test_rule_pack_rejects_unknown_registry_version(tmp_path):
    payload = json.loads(RULE_PACK_PATH.read_text(encoding="utf-8"))
    payload["registry_version"] = "registry-unknown"
    _rehash(payload)
    tampered = tmp_path / "unknown.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(InvalidRulePack, match="registry_version"):
        load_rule_pack(tampered)


@pytest.mark.parametrize(
    "mutate,error",
    [
        (
            lambda profile, rule: rule.update(binding_fields=["LANGUAGE"]),
            "only FILE_PATH",
        ),
        (
            lambda profile, rule: rule.update(groups=[[]]),
            "must not be empty",
        ),
        (
            lambda profile, rule: [
                clause.update(role="OPTIONAL") for clause in rule["groups"][0]
            ],
            "REQUIRED clause",
        ),
        (
            lambda profile, rule: profile.update(max_supported_level="L3"),
            "must equal highest rule level",
        ),
        (
            lambda profile, rule: profile.update(required_fact_types=["IMPORT"]),
            "exactly describe rule facts",
        ),
        (
            lambda profile, rule: rule["groups"][0][0]["predicates"][0].update(
                expected=[""]
            ),
            "must not be blank",
        ),
    ],
)
def test_rule_pack_semantic_invariants_fail_closed(mutate, error):
    payload = json.loads(RULE_PACK_PATH.read_text(encoding="utf-8"))
    profile = next(
        item for item in payload["technologies"] if item["tech_id"] == "react"
    )
    rule = next(item for item in profile["rules"] if item["rule_id"] == "react.l2.api")
    mutate(profile, rule)

    with pytest.raises(InvalidRulePack, match=error):
        parse_rule_pack(_rehash(payload))


def test_file_binding_prevents_cross_file_torch_backward_false_positive():
    rules = RuleSet(
        registry_version="registry-20260911.2",
        mappings=(Mapping("pytorch", "IMPORT_PATH", "PYTHON", "torch", "PREFIX"),),
        rules=(
            Rule(
                rule_id="pytorch.l2.backward",
                tech_id="pytorch",
                rule_type="L2",
                language=None,
                evaluation_scope="REPOSITORY",
                priority=1,
                clauses=(
                    Clause(
                        1,
                        1,
                        "torch-import",
                        "REQUIRED",
                        "IMPORT",
                        1,
                        (Predicate("TECH_ID", "EXACT", None, ("pytorch",)),),
                    ),
                    Clause(
                        2,
                        1,
                        "backward",
                        "REQUIRED",
                        "API_CALL",
                        1,
                        (Predicate("METHOD", "EXACT", None, ("backward",)),),
                    ),
                ),
                binding_fields=("FILE_PATH",),
            ),
        ),
    )
    elsewhere = (
        Fact(
            "IMPORT",
            {
                "MODULE": "torch",
                "LANGUAGE": "python",
                "FILE_PATH": "train.py",
                "LOCAL_NAMES": "torch",
            },
            "train.py",
            1,
        ),
        Fact(
            "API_CALL",
            {"METHOD": "backward", "RECEIVER": "turtle", "FILE_PATH": "turtle.py"},
            "turtle.py",
            2,
        ),
    )
    same_file = elsewhere + (
        Fact(
            "API_CALL",
            {"METHOD": "backward", "RECEIVER": "torch", "FILE_PATH": "train.py"},
            "train.py",
            2,
        ),
    )

    assert Judge(rules).judge(elsewhere).verdicts == ()
    assert Judge(rules).judge(same_file).verdicts[0].level == "L2"


def test_registry_snapshot_mappings_feed_the_existing_judge_models():
    registry = (
        RULE_PACK_PATH.parents[2]
        / "registry"
        / "data"
        / "technology_registry_20260911_2.json"
    )
    mappings = mappings_from_registry_artifact(registry)

    assert Mapping("pytorch", "IMPORT_PATH", "PYTHON", "torch", "PREFIX") in mappings
