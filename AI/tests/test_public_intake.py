import hashlib
import os
from inspect import signature
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from test_public_analysis_cache_integration import FakeRedis
from test_public_pipeline import fixture_batch

from github import redis_artifact_analysis_cache
from github.public_pipeline import plan_public_pipeline, run_public_pipeline
from github.snapshot_input import PublishedSnapshot, SnapshotQuality
from registry.contracts import TechnologyRegistry
from worker import public_intake
from worker.api import create_compute_app
from worker.public_intake import PublicPipelineConsumer
from worker.store import ComputeStore, Ticket, apply_migration

TOKEN = "local-c-public-test-token-only-00000000"
PREFIX = "/internal/v1/c"


@pytest.fixture
def publication():
    batch, reader = fixture_batch(2)
    identifier = uuid4().hex
    batch.dataset_snapshot_id = "fixture-public-" + identifier
    batch.pipeline_run_id = "fixture-run-" + identifier
    for row in batch.records:
        row.tree_sha = row.pinned_commit_sha
    loaded = PublishedSnapshot(
        batch=batch,
        source_root="hdfs:///fixture/" + identifier,
        source_sha256=hashlib.sha256(batch.model_dump_json().encode()).hexdigest(),
        manifest_sha256="f" * 64,
        summary_sha256="d" * 64,
        failures_sha256="e" * 64,
        quality=SnapshotQuality(
            candidate_count=3,
            snapshot_record_count=2,
            failure_count=1,
            summary_status_counts={"COMPLETE": 2, "NOT_FOUND": 1},
            snapshot_status_counts={"COMPLETE": 2},
            absent_from_snapshot_counts={"NOT_FOUND": 1},
            failed_without_snapshot_ids=(),
            complete_with_artifacts=2,
            complete_without_artifacts=0,
            declared_artifact_count=2,
            declared_artifact_type_counts={"MANIFEST": 2},
            tree_equals_commit_count=2,
        ),
    )
    registry_source = Path(
        "registry/data/technology_registry_20260908_1.json"
    ).read_bytes()
    registry = TechnologyRegistry.model_validate_json(registry_source)
    return loaded, reader, registry, hashlib.sha256(registry_source).hexdigest()


class RecordingStore:
    lease_seconds = 5

    def __init__(self):
        self.claims = []
        self.artifacts = []

    def claim(self, **kwargs):
        self.claims.append(kwargs)
        return Ticket(
            kwargs["event_id"],
            "PUBLIC_REPO",
            None,
            kwargs["occurred_at"],
            "RUNNING",
            "owned-token",
            1,
            [],
        )

    def renew(self, ticket):
        return True

    def complete(self, ticket, artifacts):
        self.artifacts.extend(artifacts)
        return [{"kind": row.kind, "snapshot_id": row.snapshot_id} for row in artifacts]

    def fail(self, ticket, code):
        pass


def consumer(publication, directory, store):
    loaded, reader, registry, registry_hash = publication
    return PublicPipelineConsumer(
        loaded, reader, registry, directory, registry_hash, store, max_records=1
    )


def test_in_progress_has_no_db_claim_or_publication(publication, tmp_path):
    store = RecordingStore()
    worker = consumer(publication, tmp_path, store)
    first = worker.poll_once(max_new_partitions=1)
    assert first["status"] == "IN_PROGRESS"
    assert first["results"] == [] and store.claims == [] and store.artifacts == []
    final = worker.poll_once(max_new_partitions=1)
    assert final["status"] == "COMPLETED"
    assert len(store.claims) == len(store.artifacts) == 1
    artifact = store.artifacts[0]
    assert artifact.kind == "PUBLIC_GITHUB" and artifact.owner is None
    assert artifact.payload["schema_version"] == "c-public-published-result/v1"
    assert artifact.payload["result"]["status"] == "INSUFFICIENT_DATA"
    assert artifact.payload["result"]["records"][0]["quality_reasons"] == [
        "TREE_SHA_EQUALS_COMMIT_SHA"
    ]
    assert artifact.payload["publication"]["quality"]["candidate_count"] == 3
    assert artifact.stream.startswith("c-public-published-result/v1:")


@pytest.fixture
def store():
    dsn = os.getenv("C_COMPUTE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set C_COMPUTE_TEST_DATABASE_URL to an isolated PostgreSQL test DB")
    apply_migration(dsn)
    return ComputeStore(dsn, lease_seconds=5)


def test_postgres_publication_replay_after_restart_has_same_snapshot(
    publication, tmp_path, store
):
    worker = consumer(publication, tmp_path, store)
    result = worker.poll_once(max_new_partitions=None)
    replay = consumer(publication, tmp_path, store).poll_once()
    assert replay["status"] == "COMPLETED"
    assert replay["event_id"] == result["event_id"]
    assert replay["results"] == result["results"]
    assert replay["reused_partitions"] == 2
    assert len(publication[1].calls) == 2
    saved = store.get_snapshot(result["results"][0]["snapshot_id"], owner=None)
    assert (
        saved["payload"]["publication"]["source_sha256"] == publication[0].source_sha256
    )
    assert saved["payload"]["result"]["analyzed_repo_count"] == 2
    assert saved["payload"]["result"]["status"] == "INSUFFICIENT_DATA"
    assert (
        store.get_head("PUBLIC_GITHUB", None, worker.stream)
        == result["results"][0]["snapshot_id"]
    )

    app = create_compute_app(store=store, token=TOKEN, registry=publication[2])
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as api_client:
        response = api_client.get(
            PREFIX + f"/snapshots/{result['results'][0]['snapshot_id']}"
        )
    assert response.status_code == 200
    assert response.json()["data"] == saved


@pytest.mark.parametrize("after_commit", [False, True])
def test_database_failure_or_commit_response_loss_reuses_local_results(
    publication, tmp_path, store, after_commit
):
    class UncertainStore:
        lease_seconds = store.lease_seconds

        def claim(self, **kwargs):
            return store.claim(**kwargs)

        def renew(self, ticket):
            return store.renew(ticket)

        def fail(self, ticket, code):
            return store.fail(ticket, code)

        def complete(self, ticket, artifacts):
            if after_commit:
                store.complete(ticket, artifacts)
            raise psycopg.OperationalError("simulated database response failure")

    with pytest.raises(psycopg.OperationalError):
        consumer(publication, tmp_path, UncertainStore()).poll_once(
            max_new_partitions=None
        )
    result = consumer(publication, tmp_path, store).poll_once()
    assert result["status"] == "COMPLETED" and result["reused_partitions"] == 2
    assert len(publication[1].calls) == 2
    saved = store.get_snapshot(result["results"][0]["snapshot_id"], owner=None)
    assert saved["payload"]["publication"]["quality"][
        "absent_from_snapshot_counts"
    ] == {"NOT_FOUND": 1}


def test_crashed_publication_waits_for_lease_then_reuses_local_parts(
    publication, tmp_path, store
):
    class SimulatedProcessExit(BaseException):
        pass

    class CrashingStore:
        lease_seconds = store.lease_seconds

        def claim(self, **kwargs):
            return store.claim(**kwargs)

        def renew(self, ticket):
            return store.renew(ticket)

        def complete(self, ticket, artifacts):
            raise SimulatedProcessExit

        def fail(self, ticket, code):
            raise AssertionError("process exit does not acknowledge DB failure")

    crashed = consumer(publication, tmp_path, CrashingStore())
    with pytest.raises(SimulatedProcessExit):
        crashed.poll_once(max_new_partitions=None)
    recovering = consumer(publication, tmp_path, store)
    waiting = recovering.poll_once()
    assert waiting["status"] == "PREPARING" and waiting["results"] == []
    assert waiting["event_id"] == crashed.event_id
    # Expire only this isolated fixture event, without a wall-clock wait.
    with store._connect() as connection:
        connection.execute(
            "UPDATE c_compute.event SET lease_until=clock_timestamp()-interval '1 second' WHERE event_id=%s",
            (crashed.event_id,),
        )
    final = recovering.poll_once()
    assert final["status"] == "COMPLETED" and final["reused_partitions"] == 2
    assert final["event_id"] == crashed.event_id
    assert len(publication[1].calls) == 2


# --- S15P21E102-350: the cache factory is the runner's, not the planner's -----


class StopAfterCapture(Exception):
    """Raised by a spy once it has recorded the call it was installed for."""


def build_consumer(publication, directory, store, **extra):
    loaded, reader, registry, registry_hash = publication
    return PublicPipelineConsumer(
        loaded, reader, registry, directory, registry_hash, store, **extra
    )


def test_consumer_is_constructible_with_the_artifact_cache_off(publication, tmp_path):
    """The default path broke too: the key was passed even when its value was None."""

    worker = build_consumer(publication, tmp_path, RecordingStore(), max_records=1)

    assert worker.pipeline_id


def test_consumer_is_constructible_with_the_artifact_cache_on(
    publication, tmp_path, monkeypatch
):
    monkeypatch.setenv("REDIS_HOST", "redis")

    worker = build_consumer(
        publication,
        tmp_path,
        RecordingStore(),
        max_records=1,
        artifact_analysis_cache_enabled=True,
    )

    assert worker.pipeline_id


def test_planner_is_never_given_a_cache_factory(publication, tmp_path, monkeypatch):
    """Shared options go to both calls, so a runner-only key must stay out of them."""

    monkeypatch.setenv("REDIS_HOST", "redis")
    seen = {}
    planner = public_intake.plan_public_pipeline

    def spy(batch, mapper, **kwargs):
        seen.update(kwargs)
        return planner(batch, mapper, **kwargs)

    monkeypatch.setattr(public_intake, "plan_public_pipeline", spy)

    build_consumer(
        publication,
        tmp_path,
        RecordingStore(),
        max_records=1,
        artifact_analysis_cache_enabled=True,
    )

    assert seen and "cache_factory" not in seen


def test_runner_is_given_the_cache_factory(publication, tmp_path, monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "redis")
    worker = build_consumer(
        publication,
        tmp_path,
        RecordingStore(),
        max_records=1,
        artifact_analysis_cache_enabled=True,
    )
    seen = {}

    def spy(*args, **kwargs):
        seen.update(kwargs)
        raise StopAfterCapture

    monkeypatch.setattr(public_intake, "run_public_pipeline", spy)

    with pytest.raises(StopAfterCapture):
        worker.poll_once(max_new_partitions=1)

    assert callable(seen["cache_factory"])


def test_planner_signature_does_not_absorb_the_runner_only_argument():
    """Fixing this by giving the planner an ignored parameter hides the coupling."""

    assert "cache_factory" not in signature(plan_public_pipeline).parameters
    assert "cache_factory" in signature(run_public_pipeline).parameters


def test_cache_enabled_publication_reaches_the_same_completion(
    publication, tmp_path, monkeypatch
):
    """The cache removes work, so it must not change what gets published.

    Constructing a consumer does not reach the code that regressed: the factory
    is the runner's, and the runner only sees it once `poll_once` gets there.
    So this drives both partitions to COMPLETED with the cache on, proves the
    factory was really built on the way, and compares the publication with the
    one the same input produces without a cache.
    """

    plain_root = tmp_path / "cache-off"
    cached_root = tmp_path / "cache-on"
    plain_root.mkdir()
    cached_root.mkdir()

    plain_store = RecordingStore()
    plain = build_consumer(publication, plain_root, plain_store, max_records=1)
    assert plain.poll_once(max_new_partitions=1)["status"] == "IN_PROGRESS"
    assert plain.poll_once(max_new_partitions=1)["status"] == "COMPLETED"

    built = []
    build_context = redis_artifact_analysis_cache.ArtifactAnalysisCacheContext.build

    def spy_build(*arguments, **keywords):
        context = build_context(*arguments, **keywords)
        built.append(context)
        return context

    # A duck-typed client keeps this off the network: the point is the wiring,
    # not Redis. Patching the factory's own entry points is what lets the real
    # runner build and use a cache without a broker.
    monkeypatch.setattr(
        redis_artifact_analysis_cache, "create_redis_client", lambda: FakeRedis()
    )
    monkeypatch.setattr(
        redis_artifact_analysis_cache.ArtifactAnalysisCacheContext,
        "build",
        staticmethod(spy_build),
    )

    cached_store = RecordingStore()
    cached = build_consumer(
        publication,
        cached_root,
        cached_store,
        max_records=1,
        artifact_analysis_cache_enabled=True,
    )
    assert cached.poll_once(max_new_partitions=1)["status"] == "IN_PROGRESS"
    final = cached.poll_once(max_new_partitions=1)

    assert final["status"] == "COMPLETED"
    assert built, "the runner never built the cache the consumer handed it"
    assert len(cached_store.claims) == len(cached_store.artifacts) == 1
    artifact = cached_store.artifacts[0]
    assert artifact.kind == "PUBLIC_GITHUB" and artifact.owner is None
    assert artifact.payload == plain_store.artifacts[0].payload
