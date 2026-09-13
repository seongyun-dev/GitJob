"""The repository consumer can publish actual C-produced personal results."""

import json
import os
import stat
import subprocess

import pytest
from test_analysis_consumer import (
    FakeCloner,
    FakeResults,
    build,
    event,
    message,
    work_target,
)
from test_analysis_depth_consumer import registry_versions

from analysis.attribution import FixtureIdentityResolver
from analysis.clone import CloneResult, PermanentCloneError
from analysis.results import SCHEMA_VERSION_V3, SCHEMA_VERSION_V4
from analysis.rulepack import (
    SCOPE_REGISTRY_PATH,
    SCOPE_RULE_PACK_PATH,
    load_rule_pack,
    mappings_from_registry_artifact,
)
from analysis.rules import RegistryStore


class WritableCleanupCloner(FakeCloner):
    def cleanup(self, into):
        path = self.work_root / into
        for item in path.rglob("*"):
            try:
                os.chmod(item, stat.S_IWRITE)
            except OSError:
                pass
        super().cleanup(into)


def test_consumer_publishes_v4_without_identity_in_the_request_event(tmp_path):
    checkout = tmp_path / work_target()
    checkout.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=checkout, check=True)
    (checkout / "main.py").write_text(
        "def hello():\n    return 'hi'\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "main.py"], cwd=checkout, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Alice",
            "-c",
            "user.email=alice@example.invalid",
            "commit",
            "-m",
            "source",
        ],
        cwd=checkout,
        check=True,
        capture_output=True,
    )
    pinned = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    registry = RegistryStore(connect=lambda: None)
    registry._cache["registry-20260911.4"] = load_rule_pack(
        SCOPE_RULE_PACK_PATH
    ).as_rule_set(mappings=mappings_from_registry_artifact(SCOPE_REGISTRY_PATH))
    results = FakeResults()

    outcome = build(
        tmp_path,
        cloner=WritableCleanupCloner(
            tmp_path, result=CloneResult(path=checkout, bytes_on_disk=128)
        ),
        registry=registry,
        results_v4=results.publisher("results.v4", SCHEMA_VERSION_V4),
        identity_resolver=FixtureIdentityResolver(
            target_login="alice", author_logins={pinned: "Alice"}
        ),
    ).handle(
        message(
            event(
                commit_sha=pinned,
                registry_version="registry-20260911.4",
            )
        )
    )

    assert outcome.action == "parsed"
    request_body = json.loads(event(commit_sha=pinned))
    assert "target_login" not in request_body["payload"]
    body = json.loads(results.published[0][2])
    assert body["schema_version"] == SCHEMA_VERSION_V4
    python = next(
        item
        for item in body["payload"]["personal_assessments"]
        if item["tech_id"] == "python"
    )
    assert python["personal_level"] is None
    assert python["attribution_status"] == "UNKNOWN"
    assert any(
        item["tech_id"] == "python"
        and item["repository_analysis_id"] == "ar_1"
        and item["attribution"] == "UNKNOWN"
        and item["attribution_missing_scope"] == ["EVIDENCE_LINE_UNAVAILABLE"]
        for item in body["payload"]["evidence"]
    )


def test_identity_resolver_does_not_upgrade_historical_v3_results(tmp_path):
    checkout = tmp_path / work_target()
    checkout.mkdir()
    (checkout / "service.py").write_text(
        "def hello():\n    return 'hi'\n", encoding="utf-8"
    )
    results = FakeResults()

    outcome = build(
        tmp_path,
        cloner=WritableCleanupCloner(
            tmp_path, result=CloneResult(path=checkout, bytes_on_disk=64)
        ),
        registry=registry_versions(),
        results_v3=results.publisher("results.v3", "repository-analysis-result/v3"),
        identity_resolver=FixtureIdentityResolver(
            target_login="alice", author_logins={}
        ),
    ).handle(message(event(registry_version="registry-20260911.3")))

    assert outcome.action == "parsed"
    body = json.loads(results.published[0][2])
    assert body["schema_version"] == "repository-analysis-result/v3"
    assert "personal_assessments" not in body["payload"]


@pytest.mark.parametrize(
    "registry_version,with_identity,expected_schema",
    [
        ("registry-20260911.3", True, SCHEMA_VERSION_V3),
        ("registry-20260911.4", False, SCHEMA_VERSION_V3),
        ("registry-20260911.4", True, SCHEMA_VERSION_V4),
    ],
)
def test_failure_result_uses_the_same_personal_v4_activation_gate(
    tmp_path, registry_version, with_identity, expected_schema
):
    v3 = FakeResults()
    v4 = FakeResults()
    consumer = build(
        tmp_path,
        cloner=FakeCloner(
            tmp_path,
            error=PermanentCloneError("REPOSITORY_NOT_FOUND", "gone"),
        ),
        results_v3=v3.publisher("results.v3", SCHEMA_VERSION_V3),
        results_v4=v4.publisher("results.v4", SCHEMA_VERSION_V4),
        identity_resolver=(
            FixtureIdentityResolver(target_login="alice", author_logins={})
            if with_identity
            else None
        ),
    )

    outcome = consumer.handle(message(event(registry_version=registry_version)))

    assert outcome.action == "failed"
    published = {
        SCHEMA_VERSION_V3: v3.published,
        SCHEMA_VERSION_V4: v4.published,
    }
    assert {schema: len(items) for schema, items in published.items()} == {
        SCHEMA_VERSION_V3: int(expected_schema == SCHEMA_VERSION_V3),
        SCHEMA_VERSION_V4: int(expected_schema == SCHEMA_VERSION_V4),
    }
    body = json.loads(published[expected_schema][0][2])
    assert body["schema_version"] == expected_schema
    assert body["payload"]["status"] == "FAILED"
