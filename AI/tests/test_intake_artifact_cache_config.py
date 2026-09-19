"""S15P21E102-347: switching the cache on is a decision, not a side effect of deploying.

The behaviour these pin down is mostly the absence of behaviour. A worker that
says nothing about the cache must ingest a publication exactly as it did before,
and a worker that asks for the cache but cannot reach Redis must still ingest it.
"""

from __future__ import annotations

import json

import pytest

from worker.intake import IntakeConfig, PublicInputConfig
from worker.public_intake import _cache_factory

REDIS_ENV = ("WEEKLY_REDIS_URL", "REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD")


def source(tmp_path, **overrides):
    return {
        "root_uri": "hdfs:///gitjob/analysis_input/github/repo_snapshot/snapshot_id=x",
        "namenode_base_url": "http://namenode:9870/webhdfs/v1",
        "checkpoint_dir": str(tmp_path / "checkpoint"),
        **overrides,
    }


@pytest.fixture(autouse=True)
def clean_redis_env(monkeypatch):
    for name in REDIS_ENV:
        monkeypatch.delenv(name, raising=False)


# --- the default is the old behaviour ----------------------------------------


def test_unspecified_field_leaves_the_cache_off(tmp_path):
    config = PublicInputConfig.model_validate(source(tmp_path))

    assert config.artifact_analysis_cache_enabled is False


def test_existing_configuration_without_the_field_still_loads(tmp_path):
    """A Production c-intake.json written before this change must stay valid."""

    payload = {
        "schema_version": "c-intake-config/v1",
        "poll_seconds": 30,
        "max_manifests": 1000,
        "public_sources": [
            source(
                tmp_path,
                artifact_root_uris=[
                    "hdfs:///gitjob/analysis_input/github/repo_snapshot"
                ],
                hdfs_user="hadoop",
                include_partial=False,
                max_records=500,
                max_declared_bytes=50_000_000,
                max_requests=100_000,
            )
        ],
    }

    config = IntakeConfig.model_validate(payload)

    assert config.public_sources[0].artifact_analysis_cache_enabled is False


def test_explicit_false_is_off(tmp_path):
    config = PublicInputConfig.model_validate(
        source(tmp_path, artifact_analysis_cache_enabled=False)
    )

    assert config.artifact_analysis_cache_enabled is False


def test_explicit_true_is_on(tmp_path):
    config = PublicInputConfig.model_validate(
        source(tmp_path, artifact_analysis_cache_enabled=True)
    )

    assert config.artifact_analysis_cache_enabled is True


def test_field_survives_a_round_trip(tmp_path):
    config = PublicInputConfig.model_validate(
        source(tmp_path, artifact_analysis_cache_enabled=True)
    )

    restored = PublicInputConfig.model_validate(json.loads(config.model_dump_json()))

    assert restored.artifact_analysis_cache_enabled is True


def test_non_boolean_is_rejected(tmp_path):
    """Strict, so a stray "true" string cannot switch this on by accident."""

    with pytest.raises(ValueError):
        PublicInputConfig.model_validate(
            source(tmp_path, artifact_analysis_cache_enabled="true")
        )


# --- the factory decides once, and never raises -------------------------------


def test_disabled_builds_nothing(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "redis")

    assert _cache_factory(enabled=False, reader=object(), registry_version="r") is None


def test_enabled_without_redis_configuration_builds_nothing(monkeypatch):
    """Asking for the cache on a worker with no Redis is not an error."""

    assert _cache_factory(enabled=True, reader=object(), registry_version="r") is None


def test_enabled_with_redis_returns_a_factory(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "redis")

    factory = _cache_factory(enabled=True, reader=object(), registry_version="r")

    assert callable(factory)


def test_each_call_builds_a_separate_context(monkeypatch):
    """Listings belong to one partition; two partitions must not share them."""

    monkeypatch.setenv("REDIS_HOST", "redis")
    factory = _cache_factory(enabled=True, reader=object(), registry_version="r")

    first, second = factory(), factory()

    assert first is not second
    assert first.validator is not second.validator
    # The client is shared on purpose: one connection, many partitions.
    assert first.cache.client is second.cache.client


def test_factory_pins_the_registry_and_parser_identity(monkeypatch):
    from github.public_analysis import (
        PUBLIC_MANIFEST_PARSER_VERSION,
        PUBLIC_PARSER_VERSION,
    )

    monkeypatch.setenv("REDIS_HOST", "redis")
    context = _cache_factory(
        enabled=True, reader=object(), registry_version="registry-20260911.4"
    )()

    assert context.cache.registry_version == "registry-20260911.4"
    assert context.cache.parser_version == (
        f"{PUBLIC_PARSER_VERSION}+{PUBLIC_MANIFEST_PARSER_VERSION}"
    )
    assert context.cache.namespace == "gitjob:weekly:artifact-analysis:v1"
    assert context.cache.ttl_seconds == 2_592_000


def test_namespace_does_not_collide_with_the_resolver_index():
    from github.redis_artifact_analysis_cache import (
        DEFAULT_NAMESPACE as ANALYSIS_NAMESPACE,
    )
    from github.redis_artifact_index import DEFAULT_NAMESPACE as INDEX_NAMESPACE

    # Same Redis DB by design; the prefixes are what keep them apart, so neither
    # may be a prefix of the other.
    assert ANALYSIS_NAMESPACE != INDEX_NAMESPACE
    assert not ANALYSIS_NAMESPACE.startswith(INDEX_NAMESPACE + ":")
    assert not INDEX_NAMESPACE.startswith(ANALYSIS_NAMESPACE + ":")


def test_client_uses_the_weekly_redis_db_convention(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "redis")
    from github.redis_artifact_analysis_cache import create_redis_client

    client = create_redis_client()

    assert client.connection_pool.connection_kwargs["db"] == 1
