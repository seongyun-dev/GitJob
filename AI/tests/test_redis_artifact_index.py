"""TDD contract tests for the Weekly Redis artifact index."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from common.webhdfs import WebHdfsResponse
from github import repo_fetch_orchestrator as orchestrator_module
from github.client import GitHubClient, HttpResponse
from github.contracts import (
    GitHubRepoSnapshot,
    RepoArtifact,
    RepoArtifactType,
    RepoCollectionStatus,
)
from github.redis_artifact_index import RedisArtifactIndex
from github.repo_fetch_orchestrator import (
    RepoActivityCandidate,
    RepoExecutionStatus,
    RepoFetchOrchestrator,
    create_redis_artifact_index,
)
from github.repo_fetch_policy import RepoFetchPolicy
from github.repo_fetch_store import (
    FileArtifactStore,
    RepoFetchCheckpoint,
    RepoSnapshotCache,
    WebHdfsArtifactStore,
)

COMMIT = "a" * 40
CONTENT_HASH = "b" * 64


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, tuple[str, int]] = {}

    def get(self, key: str):
        stored = self.values.get(key)
        return None if stored is None else stored[0]

    def set(self, key: str, value: str, *, ex: int):
        self.values[key] = (value, ex)
        return True


class FakeArtifactStore:
    def __init__(
        self,
        *,
        valid: bool = True,
        materialization_context: str = "file:///artifacts",
    ) -> None:
        self.valid = valid
        self.materialization_context = materialization_context
        self.validated: list[RepoArtifact] = []

    def validate_artifact(self, artifact: RepoArtifact) -> bool:
        self.validated.append(artifact)
        return self.valid


class ScriptedTransport:
    def __init__(self, outcomes: list[HttpResponse]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[str] = []

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        del headers, timeout
        self.calls.append(url)
        if not self.outcomes:
            raise AssertionError(f"unexpected GitHub request: {url}")
        return self.outcomes.pop(0)


RATE_HEADERS = {
    "X-RateLimit-Limit": "5000",
    "X-RateLimit-Remaining": "4999",
    "X-RateLimit-Used": "1",
    "X-RateLimit-Reset": "2000000000",
    "X-RateLimit-Resource": "core",
}


def response(
    payload: Mapping[str, object] | bytes, *, status: int = 200
) -> HttpResponse:
    body = json.dumps(payload).encode("utf-8") if isinstance(payload, Mapping) else payload
    return HttpResponse(status=status, headers=RATE_HEADERS, body=body)


def rate_control() -> HttpResponse:
    return response(
        {
            "resources": {
                "core": {
                    "limit": 5000,
                    "remaining": 4999,
                    "used": 1,
                    "reset": 2_000_000_000,
                }
            }
        }
    )


def metadata() -> HttpResponse:
    return response({"id": 7, "full_name": "octo/repo", "default_branch": "main"})


def head() -> HttpResponse:
    return response(
        {"commit": {"sha": COMMIT, "commit": {"tree": {"sha": "c" * 40}}}}
    )


def tree() -> HttpResponse:
    return response(
        {
            "sha": "c" * 40,
            "truncated": False,
            "tree": [{"path": "package.json", "type": "blob", "size": 12}],
        }
    )


def weekly_policy() -> RepoFetchPolicy:
    return RepoFetchPolicy(
        policy_version="weekly-policy-v1",
        top_n_limit=10,
        max_api_calls=100,
        max_runtime_seconds=3600,
        max_tree_entries=100,
        max_artifact_files=3,
        max_artifact_bytes=100_000,
        max_manifest_files=3,
        max_source_files=0,
        max_file_bytes=50_000,
        max_depth=8,
        source_prefix_bytes=8192,
        rate_limit_safety_threshold=10,
    )


def weekly_repo_candidate() -> RepoActivityCandidate:
    return RepoActivityCandidate(
        repo_id=7,
        repo_name="octo/repo",
        activity_count=10,
        activity_rank=1,
        activity_metric="repo_activity_weekly_event_count",
        activity_period_start=date(2026, 9, 7),
        activity_period_end=date(2026, 9, 13),
    )


def make_orchestrator(
    tmp_path: Path,
    transport: ScriptedTransport,
    *,
    artifact_store: FileArtifactStore,
    redis_index: RedisArtifactIndex | None = None,
    require_historical_head: bool = False,
) -> RepoFetchOrchestrator:
    from datetime import datetime, timezone

    return RepoFetchOrchestrator(
        client=GitHubClient("offline", transport=transport, sleep=lambda _: None),
        policy=weekly_policy(),
        artifact_store=artifact_store,
        cache=RepoSnapshotCache(tmp_path / "cache.json"),
        checkpoint=RepoFetchCheckpoint(tmp_path / "checkpoint.json"),
        dataset_snapshot_id="weekly-001",
        pipeline_run_id="run-weekly-001",
        now=lambda: datetime(2026, 9, 16, tzinfo=timezone.utc),
        redis_index=redis_index,
        require_historical_head=require_historical_head,
    )


def artifact() -> RepoArtifact:
    return RepoArtifact(
        artifact_type=RepoArtifactType.MANIFEST,
        path="package.json",
        uri="file:///artifacts/package.json",
        content_hash=CONTENT_HASH,
        size_bytes=12,
    )


def snapshot(*, artifacts: tuple[RepoArtifact, ...] = (artifact(),)) -> GitHubRepoSnapshot:
    return GitHubRepoSnapshot(
        repo_snapshot_id="weekly-001-repo-7-aaaaaaaaaaaa",
        github_repo_id=7,
        repo_full_name="octo/repo",
        activity_metric="repo_activity_weekly_event_count",
        activity_period_start=date(2026, 9, 7),
        activity_period_end=date(2026, 9, 13),
        activity_count=10,
        activity_rank=1,
        pinned_commit_sha=COMMIT,
        selected_commit_sha=COMMIT,
        sha_source="CURRENT_DEFAULT_HEAD",
        current_default_head=COMMIT,
        sha_fallback_reason="MONTH_EVENT_SHA_NOT_AVAILABLE",
        target_period="2026-09-07/2026-09-13",
        tree_sha="c" * 40,
        collection_status=RepoCollectionStatus.COMPLETE,
        tree_truncated=False,
        observed_tree_entries=1,
        artifacts=artifacts,
    )


def test_valid_index_hit_requires_durable_validation_and_sets_ttl() -> None:
    redis = FakeRedis()
    store = FakeArtifactStore()
    index = RedisArtifactIndex(
        redis,
        materialization_context=store.materialization_context,
        ttl_seconds=2_592_000,
    )

    index.put(
        cache_policy_version="weekly-policy-v1",
        repo_id=7,
        pinned_commit_sha=COMMIT,
        sha_source="CURRENT_DEFAULT_HEAD",
        artifacts=(artifact(),),
    )

    hit = index.lookup(
        cache_policy_version="weekly-policy-v1",
        repo_id=7,
        pinned_commit_sha=COMMIT,
        sha_source="CURRENT_DEFAULT_HEAD",
        artifact_store=store,
    )

    assert hit is not None
    assert hit.artifacts == (artifact(),)
    assert len(redis.values) == 1
    assert next(iter(redis.values.values()))[1] == 2_592_000
    assert store.validated == [artifact()]


def test_invalid_durable_artifact_is_a_redis_miss() -> None:
    redis = FakeRedis()
    index = RedisArtifactIndex(redis, materialization_context="file:///artifacts")
    index.put(
        cache_policy_version="weekly-policy-v1",
        repo_id=7,
        pinned_commit_sha=COMMIT,
        sha_source="CURRENT_DEFAULT_HEAD",
        artifacts=(artifact(),),
    )

    assert (
        index.lookup(
            cache_policy_version="weekly-policy-v1",
            repo_id=7,
            pinned_commit_sha=COMMIT,
            sha_source="CURRENT_DEFAULT_HEAD",
            artifact_store=FakeArtifactStore(valid=False),
        )
        is None
    )


def test_identity_mismatch_in_redis_payload_is_a_miss() -> None:
    redis = FakeRedis()
    index = RedisArtifactIndex(redis, materialization_context="file:///artifacts")
    index.put(
        cache_policy_version="weekly-policy-v1",
        repo_id=7,
        pinned_commit_sha=COMMIT,
        sha_source="CURRENT_DEFAULT_HEAD",
        artifacts=(artifact(),),
    )
    key = next(iter(redis.values))
    payload = json.loads(redis.values[key][0])
    payload["selected_commit_sha"] = "c" * 40
    redis.values[key] = (json.dumps(payload), redis.values[key][1])

    assert (
        index.lookup(
            cache_policy_version="weekly-policy-v1",
            repo_id=7,
            pinned_commit_sha=COMMIT,
            sha_source="CURRENT_DEFAULT_HEAD",
            artifact_store=FakeArtifactStore(),
        )
        is None
    )


def test_materialization_context_mismatch_is_a_redis_miss() -> None:
    redis = FakeRedis()
    index = RedisArtifactIndex(redis, materialization_context="file:///artifacts")
    index.put(
        cache_policy_version="weekly-policy-v1",
        repo_id=7,
        pinned_commit_sha=COMMIT,
        sha_source="CURRENT_DEFAULT_HEAD",
        artifacts=(artifact(),),
    )

    assert (
        index.lookup(
            cache_policy_version="weekly-policy-v1",
            repo_id=7,
            pinned_commit_sha=COMMIT,
            sha_source="CURRENT_DEFAULT_HEAD",
            artifact_store=FakeArtifactStore(
                materialization_context="hdfs://namenode:9870/gitjob/artifacts"
            ),
        )
        is None
    )


def test_redis_failures_are_fail_open() -> None:
    class BrokenRedis:
        def get(self, key: str):
            raise TimeoutError(key)

        def set(self, key: str, value: str, *, ex: int):
            raise ConnectionError(key)

    index = RedisArtifactIndex(
        BrokenRedis(), materialization_context="file:///artifacts"
    )

    assert (
        index.lookup(
            cache_policy_version="weekly-policy-v1",
            repo_id=7,
            pinned_commit_sha=COMMIT,
            sha_source="CURRENT_DEFAULT_HEAD",
            artifact_store=FakeArtifactStore(),
        )
        is None
    )
    assert (
        index.put(
            cache_policy_version="weekly-policy-v1",
            repo_id=7,
            pinned_commit_sha=COMMIT,
            sha_source="CURRENT_DEFAULT_HEAD",
            artifacts=(artifact(),),
        )
        is False
    )


def test_redis_metrics_distinguish_hit_validation_and_durable_fallback() -> None:
    redis = FakeRedis()
    index = RedisArtifactIndex(
        redis,
        materialization_context="file:///artifacts",
        monotonic=iter([0.0, 0.010]).__next__,
    )
    index.put(
        cache_policy_version="weekly-policy-v1",
        repo_id=7,
        pinned_commit_sha=COMMIT,
        sha_source="CURRENT_DEFAULT_HEAD",
        artifacts=(artifact(),),
    )

    assert (
        index.lookup(
            cache_policy_version="weekly-policy-v1",
            repo_id=7,
            pinned_commit_sha=COMMIT,
            sha_source="CURRENT_DEFAULT_HEAD",
            artifact_store=FakeArtifactStore(valid=False),
        )
        is None
    )

    assert index.metrics.lookup_count == 1
    assert index.metrics.hit_count == 1
    assert index.metrics.miss_count == 0
    assert index.metrics.durable_validation_count == 1
    assert index.metrics.durable_fallback_count == 1
    assert index.metrics.error_count == 0
    assert index.metrics.fail_open_count == 0
    assert index.metrics.percentile_ms(0.50) == 10.0


def test_redis_metrics_count_miss_and_error_fail_open() -> None:
    miss_index = RedisArtifactIndex(
        FakeRedis(),
        materialization_context="file:///artifacts",
        monotonic=iter([0.0, 0.002]).__next__,
    )
    assert (
        miss_index.lookup(
            cache_policy_version="weekly-policy-v1",
            repo_id=7,
            pinned_commit_sha=COMMIT,
            sha_source="CURRENT_DEFAULT_HEAD",
            artifact_store=FakeArtifactStore(),
        )
        is None
    )
    assert miss_index.metrics.lookup_count == 1
    assert miss_index.metrics.miss_count == 1
    assert miss_index.metrics.error_count == 0

    class BrokenRedis:
        def get(self, key: str):
            raise TimeoutError(key)

    error_index = RedisArtifactIndex(
        BrokenRedis(),
        materialization_context="file:///artifacts",
        monotonic=iter([0.0, 0.003]).__next__,
    )
    assert (
        error_index.lookup(
            cache_policy_version="weekly-policy-v1",
            repo_id=7,
            pinned_commit_sha=COMMIT,
            sha_source="CURRENT_DEFAULT_HEAD",
            artifact_store=FakeArtifactStore(),
        )
        is None
    )
    assert error_index.metrics.lookup_count == 1
    assert error_index.metrics.miss_count == 1
    assert error_index.metrics.error_count == 1
    assert error_index.metrics.fail_open_count == 1


def test_redis_metrics_handle_malformed_entry_and_latency_percentiles() -> None:
    redis = FakeRedis()
    index = RedisArtifactIndex(
        redis,
        materialization_context="file:///artifacts",
        monotonic=iter([0.0, 0.010, 0.010, 0.060]).__next__,
    )
    index.put(
        cache_policy_version="weekly-policy-v1",
        repo_id=7,
        pinned_commit_sha=COMMIT,
        sha_source="CURRENT_DEFAULT_HEAD",
        artifacts=(artifact(),),
    )
    key = next(iter(redis.values))
    redis.values[key] = ("not-json", redis.values[key][1])

    for _ in range(2):
        assert (
            index.lookup(
                cache_policy_version="weekly-policy-v1",
                repo_id=7,
                pinned_commit_sha=COMMIT,
                sha_source="CURRENT_DEFAULT_HEAD",
                artifact_store=FakeArtifactStore(),
            )
            is None
        )

    assert index.metrics.lookup_count == 2
    assert index.metrics.miss_count == 2
    assert index.metrics.error_count == 2
    assert index.metrics.fail_open_count == 2
    assert index.metrics.percentile_ms(0.50) == 10.0
    assert index.metrics.percentile_ms(0.95) == 50.0
    assert index.metrics.hit_rate == 0.0


def test_empty_or_historical_results_are_not_indexed() -> None:
    redis = FakeRedis()
    index = RedisArtifactIndex(redis, materialization_context="file:///artifacts")

    assert index.put(
        cache_policy_version="weekly-policy-v1",
        repo_id=7,
        pinned_commit_sha=COMMIT,
        sha_source="CURRENT_DEFAULT_HEAD",
        artifacts=(),
    ) is False
    assert index.put(
        cache_policy_version="historical-policy-v1",
        repo_id=7,
        pinned_commit_sha=COMMIT,
        sha_source="MONTH_EVENT_SHA",
        artifacts=(artifact(),),
    ) is False
    assert redis.values == {}


def test_snapshot_cache_context_prevents_file_to_hdfs_reuse(tmp_path: Path) -> None:
    cache = RepoSnapshotCache(tmp_path / "cache.json")
    cache.put(
        policy_version="weekly-policy-v1",
        materialization_context="file:///artifacts",
        record=snapshot(),
    )

    assert (
        cache.get(
            policy_version="weekly-policy-v1",
            materialization_context="file:///artifacts",
            repo_id=7,
            pinned_commit_sha=COMMIT,
        )
        is not None
    )
    assert (
        cache.get(
            policy_version="weekly-policy-v1",
            materialization_context="hdfs://namenode:9870/gitjob/artifacts",
            repo_id=7,
            pinned_commit_sha=COMMIT,
        )
        is None
    )


def test_snapshot_cache_context_prevents_hdfs_namespace_reuse(tmp_path: Path) -> None:
    cache = RepoSnapshotCache(tmp_path / "cache.json")
    cache.put(
        policy_version="weekly-policy-v1",
        materialization_context="http://namenode-a:9870|root=/gitjob/artifacts",
        record=snapshot(),
    )

    assert (
        cache.get(
            policy_version="weekly-policy-v1",
            materialization_context="http://namenode-b:9870|root=/gitjob/artifacts",
            repo_id=7,
            pinned_commit_sha=COMMIT,
        )
        is None
    )


def test_file_artifact_store_validates_existence_size_and_sha(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "artifacts")
    content = b'{"name":"repo"}'
    uri = store.store(
        policy_version="weekly-policy-v1",
        repo_id=7,
        pinned_commit_sha=COMMIT,
        path="package.json",
        content=content,
    )
    valid = RepoArtifact(
        artifact_type=RepoArtifactType.MANIFEST,
        path="package.json",
        uri=uri,
        content_hash=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
    )

    assert store.validate_artifact(valid) is True
    assert store.validate_artifact(valid.model_copy(update={"size_bytes": 1})) is False
    assert store.validate_artifact(
        valid.model_copy(update={"content_hash": "0" * 64})
    ) is False
    assert store.validate_artifact(valid.model_copy(update={"uri": "hdfs:///x"})) is False


def test_weekly_orchestrator_uses_valid_redis_hit_without_tree_or_raw_calls(
    tmp_path: Path,
) -> None:
    store = FileArtifactStore(tmp_path / "artifacts")
    content = b'{"name":"repo"}'
    policy = weekly_policy()
    uri = store.store(
        policy_version=policy.cache_identity,
        repo_id=7,
        pinned_commit_sha=COMMIT,
        path="package.json",
        content=content,
    )
    cached_artifact = RepoArtifact(
        artifact_type=RepoArtifactType.MANIFEST,
        path="package.json",
        uri=uri,
        content_hash=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
    )
    redis = FakeRedis()
    index = RedisArtifactIndex(
        redis, materialization_context=store.materialization_context
    )
    index.put(
        cache_policy_version=policy.cache_identity,
        repo_id=7,
        pinned_commit_sha=COMMIT,
        sha_source="CURRENT_DEFAULT_HEAD",
        artifacts=(cached_artifact,),
    )
    transport = ScriptedTransport([metadata(), head()])

    result = make_orchestrator(
        tmp_path,
        transport,
        artifact_store=store,
        redis_index=index,
    ).fetch_repo(weekly_repo_candidate())

    assert result.status is RepoExecutionStatus.REUSED
    assert result.record is not None
    assert result.record.artifacts == (cached_artifact,)
    assert len(transport.calls) == 2


def test_historical_orchestrator_rejects_redis_index(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "artifacts")
    index = RedisArtifactIndex(
        FakeRedis(), materialization_context=store.materialization_context
    )
    with pytest.raises(ValueError, match="Historical"):
        make_orchestrator(
            tmp_path,
            ScriptedTransport([]),
            artifact_store=store,
            redis_index=index,
            require_historical_head=True,
        )


def test_new_extraction_publishes_positive_artifact_index_entry(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "artifacts")
    redis = FakeRedis()
    index = RedisArtifactIndex(
        redis, materialization_context=store.materialization_context
    )
    transport = ScriptedTransport(
        [metadata(), head(), tree(), response(b'{"name":"repo"}')]
    )

    result = make_orchestrator(
        tmp_path,
        transport,
        artifact_store=store,
        redis_index=index,
    ).fetch_repo(weekly_repo_candidate())

    assert result.status is RepoExecutionStatus.COMPLETE
    assert len(redis.values) == 1


def test_run_summary_includes_additive_redis_metrics(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "artifacts")
    index = RedisArtifactIndex(
        FakeRedis(), materialization_context=store.materialization_context
    )
    transport = ScriptedTransport(
        [rate_control(), metadata(), head(), tree(), response(b'{"name":"repo"}')]
    )

    summary = make_orchestrator(
        tmp_path,
        transport,
        artifact_store=store,
        redis_index=index,
    ).run([weekly_repo_candidate()]).summary()

    assert summary["schema_version"] == "github-repo-fetch-run-summary/v1"
    assert summary["redis_enabled"] is True
    assert summary["redis_lookup_count"] == 1
    assert summary["redis_hit_count"] == 0
    assert summary["redis_miss_count"] == 1
    assert summary["redis_hit_rate"] == 0.0
    assert summary["redis_lookup_latency_p50_ms"] is not None
    assert summary["redis_lookup_latency_p95_ms"] is not None
    assert summary["redis_error_count"] == 0
    assert summary["redis_fail_open_count"] == 0
    assert summary["redis_durable_validation_count"] == 0
    assert summary["redis_durable_fallback_count"] == 0


def test_redis_write_failure_does_not_change_durable_publication(
    tmp_path: Path,
) -> None:
    class WriteBrokenRedis:
        def get(self, key: str):
            del key

        def set(self, key: str, value: str, *, ex: int):
            del key, value, ex
            raise ConnectionError("Redis unavailable")

    store = FileArtifactStore(tmp_path / "artifacts")
    index = RedisArtifactIndex(
        WriteBrokenRedis(), materialization_context=store.materialization_context
    )
    transport = ScriptedTransport(
        [metadata(), head(), tree(), response(b'{"name":"repo"}')]
    )

    result = make_orchestrator(
        tmp_path,
        transport,
        artifact_store=store,
        redis_index=index,
    ).fetch_repo(weekly_repo_candidate())

    assert result.status is RepoExecutionStatus.COMPLETE
    assert result.record is not None
    assert len(result.record.artifacts) == 1
    assert index.metrics.error_count == 1
    assert index.metrics.fail_open_count == 1


def test_redis_factory_defaults_to_db_one_and_configured_ttl(monkeypatch) -> None:
    monkeypatch.delenv("WEEKLY_REDIS_URL", raising=False)
    monkeypatch.setenv("REDIS_HOST", "redis")
    monkeypatch.delenv("WEEKLY_REDIS_DB", raising=False)
    monkeypatch.setenv("WEEKLY_REDIS_ARTIFACT_INDEX_TTL_SECONDS", "123")

    index = create_redis_artifact_index(materialization_context="file:///artifacts")

    assert index is not None
    assert index.ttl_seconds == 123
    assert index.client.connection_pool.connection_kwargs["db"] == 1


class WebHdfsValidationTransport:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def request(
        self,
        method: str,
        url: str,
        *,
        body: Path | bytes | None = None,
        timeout: float,
    ) -> WebHdfsResponse:
        del method, body, timeout
        if "op=GETFILESTATUS" in url:
            return WebHdfsResponse(
                status=200,
                headers={},
                body=json.dumps(
                    {"FileStatus": {"type": "FILE", "length": len(self.content)}}
                ).encode("utf-8"),
            )
        if "op=OPEN" in url:
            return WebHdfsResponse(status=200, headers={}, body=self.content)
        raise AssertionError(f"unexpected WebHDFS request: {url}")


def test_webhdfs_artifact_store_validates_namespace_size_and_sha() -> None:
    content = b"durable artifact"
    store = WebHdfsArtifactStore(
        base_url="http://namenode:9870/webhdfs/v1",
        root="hdfs:///gitjob/artifacts",
        transport=WebHdfsValidationTransport(content),
    )
    valid = RepoArtifact(
        artifact_type=RepoArtifactType.MANIFEST,
        path="package.json",
        uri="hdfs:///gitjob/artifacts/package.json",
        content_hash=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
    )

    assert store.validate_artifact(valid) is True
    assert store.validate_artifact(
        valid.model_copy(update={"uri": "hdfs:///outside/package.json"})
    ) is False
    assert store.validate_artifact(
        valid.model_copy(update={"uri": "hdfs://other/gitjob/artifacts/package.json"})
    ) is False


# --- S15P21E102-323: Production default activation -------------------------


class _StubArtifactStore:
    materialization_context = "hdfs://nn/gitjob/artifacts"


def test_create_orchestrator_refuses_silent_redis_disable(monkeypatch) -> None:
    """Asking for the index and getting none must fail, not run without it.

    A Weekly run started in a service with no REDIS_* block built no index and
    reported every Redis metric as zero, which reads exactly like a cold
    namespace. Nothing downstream could tell the two apart, so the
    misconfiguration is refused where it is still cheap to fix.
    """

    monkeypatch.setattr(
        orchestrator_module, "create_artifact_store", lambda _: _StubArtifactStore()
    )
    monkeypatch.setattr(
        orchestrator_module, "create_redis_artifact_index", lambda **_: None
    )

    arguments = SimpleNamespace(weekly_redis_enabled=True)

    with pytest.raises(ValueError) as excinfo:
        orchestrator_module.create_orchestrator(arguments, token="t")

    message = str(excinfo.value)
    assert "enable-redis-artifact-index" in message
    # The message has to name the service, because "set REDIS_HOST" alone does
    # not tell an operator which compose service actually carries it.
    assert "worker" in message
    assert "collector" in message


def test_redis_factory_uses_production_namespace_not_benchmark(monkeypatch) -> None:
    monkeypatch.delenv("WEEKLY_REDIS_URL", raising=False)
    monkeypatch.setenv("REDIS_HOST", "redis")
    monkeypatch.delenv("WEEKLY_REDIS_ARTIFACT_INDEX_NAMESPACE", raising=False)
    monkeypatch.delenv("WEEKLY_REDIS_DB", raising=False)

    index = create_redis_artifact_index(materialization_context="file:///artifacts")

    assert index is not None
    assert index.namespace == "gitjob:weekly:artifact-index:v1"
    assert "benchmark" not in index.namespace
    assert index.client.connection_pool.connection_kwargs["db"] == 1


def test_weekly_artifact_resolver_wrapper_pins_service_and_contract() -> None:
    """The wrapper is the Production entry point, so its contract is asserted.

    `collector` would silently skip the index and the Historical Top-10000 pool
    would silently replace the Weekly 1500, and neither shows up in the output.
    """

    wrapper = (
        Path(__file__).resolve().parents[2]
        / "Infra"
        / "scripts"
        / "weekly-artifact-resolver.sh"
    )
    text = wrapper.read_text(encoding="utf-8")

    assert "--enable-redis-artifact-index" in text
    # the service the resolver is handed to, not a mention in a comment
    assert "\n  worker \\\n" in text
    assert 'pool_limit="${WEEKLY_CANDIDATE_POOL_LIMIT:-1500}"' in text
    assert 'quota="${WEEKLY_ARTIFACT_QUOTA:-100}"' in text
    assert 'batch_size="${WEEKLY_CANDIDATE_BATCH_SIZE:-1}"' in text
    # benchmark isolation, judged on what the script executes: the comments do
    # name the benchmark namespace, precisely to say it is never used here.
    executable = [
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    ]
    assert not any("WEEKLY_REDIS_DB" in line for line in executable)
    assert not any("gitjob:benchmark" in line for line in executable)


def test_compose_worker_enables_weekly_redis_index_by_default() -> None:
    compose = Path(__file__).resolve().parents[2] / "Infra" / "compose" / "compose.yaml"
    text = compose.read_text(encoding="utf-8")

    assert (
        "WEEKLY_REDIS_ARTIFACT_INDEX_ENABLED: ${WEEKLY_REDIS_ARTIFACT_INDEX_ENABLED:-1}"
        in text
    )
    # Declaring these would let a benchmark shell environment reach the
    # container; the code defaults are the Production contract.
    assert "WEEKLY_REDIS_DB:" not in text
    assert "WEEKLY_REDIS_ARTIFACT_INDEX_NAMESPACE:" not in text
