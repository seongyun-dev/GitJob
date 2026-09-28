"""Actual depth extraction, versioned result routing, and failure redelivery."""

import json

import pytest
from test_analysis_consumer import (
    EmptyRegistry,
    FakeClaims,
    FakeCloner,
    FakeResults,
    build,
    event,
    message,
)

from analysis.clone import CloneResult, PermanentCloneError, TransientCloneError
from analysis.results import SCHEMA_VERSION, SCHEMA_VERSION_V2, SCHEMA_VERSION_V3
from analysis.rulepack import (
    DEPTH_RULE_PACK_PATH,
    RULE_PACK_PATH,
    load_rule_pack,
    mappings_from_registry_artifact,
)
from analysis.rules import RegistryStore, UnknownRegistryVersion


def registry_versions():
    registry = RegistryStore(connect=lambda: None)
    for path, suffix in ((RULE_PACK_PATH, "2"), (DEPTH_RULE_PACK_PATH, "3")):
        registry._cache[f"registry-20260911.{suffix}"] = load_rule_pack(
            path
        ).as_rule_set(
            mappings=mappings_from_registry_artifact(
                path.parents[2]
                / "registry/data"
                / f"technology_registry_20260911_{suffix}.json"
            )
        )
    legacy = "technology-registry/v1"
    registry._cache[legacy] = EmptyRegistry().load(legacy)
    return registry


@pytest.mark.parametrize(
    "version,schema",
    [
        ("technology-registry/v1", SCHEMA_VERSION),
        ("registry-20260911.2", SCHEMA_VERSION_V2),
        ("registry-20260911.3", SCHEMA_VERSION_V3),
    ],
)
def test_mixed_worker_routes_real_source_by_requested_version(
    tmp_path, version, schema
):
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
    results = {
        key: FakeResults()
        for key in (SCHEMA_VERSION, SCHEMA_VERSION_V2, SCHEMA_VERSION_V3)
    }
    outcome = build(
        tmp_path,
        cloner=FakeCloner(
            tmp_path, result=CloneResult(path=checkout, bytes_on_disk=256)
        ),
        registry=registry_versions(),
        results=results[SCHEMA_VERSION].publisher("results.v1", SCHEMA_VERSION),
        results_v2=results[SCHEMA_VERSION_V2].publisher(
            "results.v2", SCHEMA_VERSION_V2
        ),
        results_v3=results[SCHEMA_VERSION_V3].publisher(
            "results.v3", SCHEMA_VERSION_V3
        ),
    ).handle(message(event(registry_version=version)))
    assert outcome.action == "parsed"
    assert {key: len(value.published) for key, value in results.items()} == {
        key: int(key == schema) for key in results
    }
    body = json.loads(results[schema].published[0][2])
    assert body["schema_version"] == schema
    if schema == SCHEMA_VERSION_V3:
        assert (
            next(
                item["level"]
                for item in body["payload"]["technologies"]
                if item["tech_id"] == "python"
            )
            == "L3"
        )
        assert body["payload"]["stats"]["syntax_node_count"] > 0
        assert any(
            item["fact_type"] == "SYNTAX_NODE" for item in body["payload"]["evidence"]
        )
        assert (
            body["payload"]["rule_pack_content_sha256"]
            == load_rule_pack(DEPTH_RULE_PACK_PATH).content_sha256
        )
    else:
        assert all(
            item["fact_type"] != "SYNTAX_NODE" for item in body["payload"]["evidence"]
        )


@pytest.mark.parametrize("failure", ["clone", "retry_budget", "unknown_registry"])
def test_depth_failure_publish_error_never_finishes_claim(tmp_path, failure):
    class MissingRegistry:
        def load(self, _version):
            raise UnknownRegistryVersion("not installed")

    cloner = FakeCloner(tmp_path)
    if failure == "clone":
        cloner = FakeCloner(
            tmp_path, error=PermanentCloneError("REPOSITORY_NOT_FOUND", "gone")
        )
    elif failure == "retry_budget":
        cloner = FakeCloner(
            tmp_path, error=TransientCloneError("CLONE_TIMEOUT", "timeout")
        )
    claims = FakeClaims(token=5)
    results = FakeResults(fail=True)
    kwargs = {"claims": claims, "cloner": cloner, "registry": MissingRegistry()}
    request = message(event(registry_version="registry-20260911.3"))
    with pytest.raises(RuntimeError, match="results broker is down"):
        build(
            tmp_path,
            **kwargs,
            results_v3=results.publisher("results.v3", SCHEMA_VERSION_V3),
        ).handle(request)
    assert claims.finished == []
    recovered = FakeResults()
    outcome = build(
        tmp_path,
        **kwargs,
        results_v3=recovered.publisher("results.v3", SCHEMA_VERSION_V3),
    ).handle(request)
    assert outcome.action == "failed"
    assert len(claims.finished) == 1
    body = json.loads(recovered.published[0][2])
    assert body["schema_version"] == SCHEMA_VERSION_V3
    assert body["payload"]["status"] == "FAILED"


def test_depth_missing_destination_is_explicit_failure(tmp_path):
    results = FakeResults()
    outcome = build(
        tmp_path,
        registry=registry_versions(),
        results=results.publisher("results.v1", SCHEMA_VERSION),
    ).handle(message(event(registry_version="registry-20260911.3")))
    assert outcome.error_code == "UNSUPPORTED_RESULT_SCHEMA"
    body = json.loads(results.published[0][2])
    assert body["schema_version"] == SCHEMA_VERSION
    assert body["payload"]["error_code"] == "UNSUPPORTED_RESULT_SCHEMA"
