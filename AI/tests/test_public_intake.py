import hashlib
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from test_public_pipeline import fixture_batch

from github.snapshot_input import PublishedSnapshot, SnapshotQuality
from registry.contracts import TechnologyRegistry
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
