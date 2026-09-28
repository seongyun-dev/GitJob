"""The callable-scoped pack is additive and leaves .2/.3 immutable."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter

import pytest
from pydantic import ValidationError
from test_analysis_consumer import FakeCloner, FakeResults, build, event, message
from test_analysis_result_v3 import depth_result

from analysis.clone import CloneResult
from analysis.results import (
    SCHEMA_VERSION,
    SCHEMA_VERSION_V3,
    RepositoryAnalysisResultV3,
    schema_for_rule_pack,
)
from analysis.rulepack import (
    DEPTH_RULE_PACK_PATH,
    RULE_PACK_PATH,
    SCOPE_REGISTRY_PATH,
    SCOPE_RULE_PACK_PATH,
    InvalidRulePack,
    load_rule_pack,
    mappings_from_registry_artifact,
    parse_rule_pack,
)
from analysis.rules import RegistryStore
from registry.contracts import load_registry

IMMUTABLE_LF_BYTE_HASHES = {
    "registry/data/technology_registry_20260911_2.json": (
        "dddc0895003ad57b6fac9b620fd15a32b63cd8a9beab3bd183a88f845970fe8e"
    ),
    "registry/data/technology_registry_20260911_3.json": (
        "ac2a0724ed9aac1c8e51809d069ee6bd7fbc711d1f14c3374a124f72fcc48d1e"
    ),
    "analysis/data/rule_pack_20260911_2.json": (
        "dd8c5e95d94eb00c422bd118ce1bbc1e80703485956b15c16f8765bd6a9ebbed"
    ),
    "analysis/data/rule_pack_20260911_3.json": (
        "a04c3d948b773bed9585950f437b8046fc80a0998449b23ef65b3142c6323abb"
    ),
}


def _payload(path):
    return json.loads(path.read_text("utf-8"))


def _canonical_hash(payload):
    content = {key: value for key, value in payload.items() if key != "content_sha256"}
    return hashlib.sha256(
        json.dumps(
            content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _kafka_l3(payload):
    profile = next(
        item for item in payload["technologies"] if item["tech_id"] == "apache-kafka"
    )
    return next(rule for rule in profile["rules"] if rule["rule_type"] == "L3")


def test_previous_registry_and_rule_pack_artifacts_remain_byte_identical():
    ai_root = RULE_PACK_PATH.parents[2]
    for relative, expected in IMMUTABLE_LF_BYTE_HASHES.items():
        # Git stores these JSON artifacts with LF. Windows may materialize CRLF,
        # so normalize only line endings before asserting the immutable blob bytes.
        content = (ai_root / relative).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(content).hexdigest() == expected


def test_scope_registry_and_pack_are_the_exact_additive_successors():
    old_registry = load_registry(
        RULE_PACK_PATH.parents[2] / "registry/data/technology_registry_20260911_3.json",
        repository_root=RULE_PACK_PATH.parents[3],
    )
    new_registry = load_registry(
        SCOPE_REGISTRY_PATH, repository_root=RULE_PACK_PATH.parents[3]
    )
    old_registry_content = old_registry.model_dump(mode="json")
    new_registry_content = new_registry.model_dump(mode="json")
    old_registry_content.pop("registry_version")
    new_registry_content.pop("registry_version")
    assert old_registry_content == new_registry_content
    assert new_registry.registry_version == "registry-20260911.4"

    old_pack = _payload(DEPTH_RULE_PACK_PATH)
    new_pack = _payload(SCOPE_RULE_PACK_PATH)
    assert _kafka_l3(old_pack)["binding_fields"] == ["FILE_PATH", "COMPONENT"]
    assert _kafka_l3(new_pack)["binding_fields"] == ["FILE_PATH", "FUNCTION"]
    comparable = copy.deepcopy(new_pack)
    comparable["rule_pack_version"] = old_pack["rule_pack_version"]
    comparable["registry_version"] = old_pack["registry_version"]
    comparable["content_sha256"] = old_pack["content_sha256"]
    _kafka_l3(comparable)["binding_fields"] = ["FILE_PATH", "COMPONENT"]
    assert comparable == old_pack
    assert new_pack["content_sha256"] == _canonical_hash(new_pack)
    assert load_rule_pack(SCOPE_RULE_PACK_PATH, registry=new_registry)
    rules = [rule for profile in new_pack["technologies"] for rule in profile["rules"]]
    assert len(rules) == 145
    ceilings = Counter(
        profile["max_supported_level"] for profile in new_pack["technologies"]
    )
    assert ceilings == {"L1": 8, "L2": 9, "L3": 27}
    assert {
        "L1": len(new_pack["technologies"]),
        "L2": ceilings["L2"] + ceilings["L3"],
        "L3": ceilings["L3"],
    } == {"L1": 44, "L2": 36, "L3": 27}


def test_scope_pack_rejects_cross_version_and_unbound_function():
    payload = _payload(SCOPE_RULE_PACK_PATH)
    payload["registry_version"] = "registry-20260911.3"
    payload["content_sha256"] = _canonical_hash(payload)
    with pytest.raises(InvalidRulePack, match="registry_version"):
        parse_rule_pack(payload)

    payload = _payload(SCOPE_RULE_PACK_PATH)
    _kafka_l3(payload)["binding_fields"] = ["FUNCTION"]
    payload["content_sha256"] = _canonical_hash(payload)
    with pytest.raises(InvalidRulePack, match="FILE_PATH"):
        parse_rule_pack(payload)


def test_result_v3_reads_the_immutable_pre_scope_writer_fixture():
    fixture = (
        RULE_PACK_PATH.parents[2]
        / "tests/fixtures/repository-analysis-result-v3-base-c43f76d.json"
    )
    historical = RepositoryAnalysisResultV3.model_validate_json(
        fixture.read_text("utf-8")
    )
    assert historical.payload.registry_version == "registry-20260911.3"
    assert historical.payload.rule_pack_version == "rule-pack-20260911.3"
    assert all(
        "FUNCTION" not in fact.fact_payload for fact in historical.payload.evidence
    )


def test_result_v3_accepts_both_exact_depth_pairs_and_rejects_cross_pair():
    depth_v3 = depth_result()
    assert RepositoryAnalysisResultV3.model_validate(depth_v3.model_dump()) == depth_v3

    payload = depth_v3.model_dump(mode="json")
    payload["payload"]["registry_version"] = "registry-20260911.4"
    payload["payload"]["rule_pack_version"] = "rule-pack-20260911.4"
    payload["payload"]["rule_pack_content_sha256"] = load_rule_pack(
        SCOPE_RULE_PACK_PATH
    ).content_sha256
    current = RepositoryAnalysisResultV3.model_validate(payload)
    assert current.payload.registry_version == "registry-20260911.4"
    assert schema_for_rule_pack("rule-pack-20260911.4") == SCHEMA_VERSION_V3

    payload["payload"]["registry_version"] = "registry-20260911.3"
    with pytest.raises(ValidationError, match="version pair"):
        RepositoryAnalysisResultV3.model_validate(payload)


def test_scope_pack_routes_through_v3_and_keeps_structural_facts(tmp_path):
    checkout = tmp_path / "source"
    checkout.mkdir()
    (checkout / "service.py").write_text(
        "import asyncio\n"
        "async def supervise(coro):\n"
        "    task = asyncio.create_task(coro)\n"
        "    try:\n"
        "        return await asyncio.wait_for(task, timeout=2)\n"
        "    finally:\n"
        "        task.cancel()\n",
        encoding="utf-8",
    )
    pack = load_rule_pack(SCOPE_RULE_PACK_PATH)
    registry = RegistryStore(connect=lambda: None)
    registry._cache[pack.registry_version] = pack.as_rule_set(
        mappings=mappings_from_registry_artifact(SCOPE_REGISTRY_PATH)
    )
    v1 = FakeResults()
    v3 = FakeResults()

    outcome = build(
        tmp_path,
        cloner=FakeCloner(
            tmp_path, result=CloneResult(path=checkout, bytes_on_disk=256)
        ),
        registry=registry,
        results=v1.publisher("results.v1", SCHEMA_VERSION),
        results_v3=v3.publisher("results.v3", SCHEMA_VERSION_V3),
    ).handle(message(event(registry_version="registry-20260911.4")))

    assert outcome.action == "parsed"
    assert not v1.published
    body = json.loads(v3.published[0][2])
    assert body["schema_version"] == SCHEMA_VERSION_V3
    assert body["payload"]["registry_version"] == "registry-20260911.4"
    assert body["payload"]["rule_pack_version"] == "rule-pack-20260911.4"
    assert any(
        item["fact_type"] == "SYNTAX_NODE" for item in body["payload"]["evidence"]
    )
