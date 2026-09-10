"""PostgreSQL integration checks; never target an implicit/shared database."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from worker.store import (
    MIGRATION_VERSION,
    Artifact,
    ComputeStore,
    IdempotencyConflict,
    LeaseLost,
    apply_migration,
)


@pytest.fixture
def store():
    dsn = os.environ.get("C_COMPUTE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set C_COMPUTE_TEST_DATABASE_URL to an isolated PostgreSQL test DB")
    apply_migration(dsn)
    return ComputeStore(dsn, lease_seconds=5)


def claim(store, event_id=None, *, at=None, body=None):
    return store.claim(
        event_id=event_id or str(uuid4()),
        kind="ANALYSIS",
        owner="123",
        occurred_at=at or datetime.now(UTC),
        request=body or {"analysis_id": "a1"},
    )


def artifact(value=1, stream=None):
    return Artifact(
        kind="RECOMMENDATION",
        owner="123",
        payload={"value": value},
        stream=stream or str(uuid4()),
    )


def test_completion_byte_binding_is_atomic_and_immutable(store):
    fixed, fresh = str(uuid4()), str(uuid4())
    original = ("a" * 64, "b" * 64)
    changed = ("c" * 64, "d" * 64)
    store.bind_job_inputs({fixed: original})
    store.bind_job_inputs({fixed: original})
    with pytest.raises(IdempotencyConflict):
        store.bind_job_inputs({fixed: changed, fresh: original})
    # A conflicting input set does not pin unrelated new paths in half a transaction.
    store.bind_job_inputs({fixed: original, fresh: changed})
    with pytest.raises(IdempotencyConflict):
        store.bind_job_inputs({fresh: original})


def test_concurrent_different_completion_bytes_have_only_one_accepted_binding(store):
    path = str(uuid4())

    def bind(index):
        try:
            store.bind_job_inputs({path: (str(index) * 64, "a" * 64)})
            return index
        except IdempotencyConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(bind, [1, 2]))
    assert sum(value is not None for value in outcomes) == 1
    winner = next(value for value in outcomes if value is not None)
    store.bind_job_inputs({path: (str(winner) * 64, "a" * 64)})


def test_atomic_completion_replay_and_owner_scope(store):
    ticket = claim(store)
    row = artifact()
    references = store.complete(ticket, [row])
    replay = store.claim(
        event_id=ticket.event_id,
        kind="ANALYSIS",
        owner="123",
        occurred_at=ticket.occurred_at,
        request={"analysis_id": "a1"},
    )
    assert replay.status == "COMPLETED"
    assert replay.results == references
    assert store.get_snapshot(references[0]["snapshot_id"], owner="123")["payload"] == {
        "value": 1
    }
    assert store.get_snapshot(references[0]["snapshot_id"], owner="456") is None
    assert store.get_snapshot(references[0]["snapshot_id"], owner=None) is None


def test_reused_event_different_content_or_owner_conflicts(store):
    ticket = claim(store)
    for owner, body in [
        ("123", {"analysis_id": "other"}),
        ("456", {"analysis_id": "a1"}),
    ]:
        with pytest.raises(IdempotencyConflict):
            store.claim(
                event_id=ticket.event_id,
                kind="ANALYSIS",
                owner=owner,
                occurred_at=ticket.occurred_at,
                request=body,
            )


def test_concurrent_delivery_busy_then_failed_retry(store):
    ticket = claim(store)
    replay = store.claim(
        event_id=ticket.event_id,
        kind="ANALYSIS",
        owner="123",
        occurred_at=ticket.occurred_at,
        request={"analysis_id": "a1"},
    )
    assert replay.status == "RUNNING" and replay.token is None
    store.fail(ticket, "COMPUTE_FAILED")
    retry = store.claim(
        event_id=ticket.event_id,
        kind="ANALYSIS",
        owner="123",
        occurred_at=ticket.occurred_at,
        request={"analysis_id": "a1"},
    )
    assert retry.token and retry.token != ticket.token and retry.attempt == 2
    with pytest.raises(LeaseLost):
        store.complete(ticket, [artifact()])
    assert store.complete(retry, [artifact()])


def test_old_event_does_not_move_current_pointer_backwards(store):
    stream = str(uuid4())
    now = datetime.now(UTC)
    newer = claim(store, at=now)
    new_ref = store.complete(newer, [artifact(2, stream)])[0]
    older = claim(store, at=now - timedelta(days=1))
    old_ref = store.complete(older, [artifact(1, stream)])[0]
    assert old_ref != new_ref
    assert store.get_head("RECOMMENDATION", "123", stream) == new_ref["snapshot_id"]


def test_public_snapshot_is_not_visible_under_forged_personal_scope(store):
    ticket = store.claim(
        event_id=str(uuid4()),
        kind="JOB_BATCH",
        owner=None,
        occurred_at=datetime.now(UTC),
        request={"batch": 1},
    )
    ref = store.complete(ticket, [Artifact("COHORT", None, {"jobs": []}, "job")])[0]
    assert store.get_snapshot(ref["snapshot_id"], owner=None)
    assert store.get_snapshot(ref["snapshot_id"], owner="123") is None


def test_expired_attempt_is_fenced_and_recovered_without_waiting(store):
    ticket = claim(store)
    with psycopg.connect(os.environ["C_COMPUTE_TEST_DATABASE_URL"]) as conn:
        conn.execute(
            "UPDATE c_compute.event SET lease_until = clock_timestamp() - interval '1 second' WHERE event_id = %s",
            (ticket.event_id,),
        )
    with pytest.raises(LeaseLost):
        store.complete(ticket, [artifact()])
    retry = store.claim(
        event_id=ticket.event_id,
        kind="ANALYSIS",
        owner="123",
        occurred_at=ticket.occurred_at,
        request={"analysis_id": "a1"},
    )
    assert retry.token and retry.attempt == 2
    store.fail(ticket, "OLD_ATTEMPT")
    assert store.complete(retry, [artifact()])


def test_parallel_delivery_has_exactly_one_owner(store):
    event_id, now = str(uuid4()), datetime.now(UTC)
    with ThreadPoolExecutor(max_workers=4) as pool:
        tickets = list(pool.map(lambda _: claim(store, event_id, at=now), range(4)))
    assert sum(ticket.token is not None for ticket in tickets) == 1


def test_artifact_failure_rolls_back_all_results_and_event_completion(store):
    ticket = store.claim(
        event_id=str(uuid4()),
        kind="JOB_BATCH",
        owner=None,
        occurred_at=datetime.now(UTC),
        request={"batch": "rollback"},
    )
    first = Artifact(
        "COHORT", None, {"jobs": [], "test_event": ticket.event_id}, str(uuid4())
    )
    second = Artifact("DEMAND", None, {"invalid_jsonb": "\x00"}, str(uuid4()))
    with pytest.raises(psycopg.Error):
        store.complete(ticket, [first, second])
    assert store.get_snapshot(first.snapshot_id, owner=None) is None
    retry = store.claim(
        event_id=ticket.event_id,
        kind="JOB_BATCH",
        owner=None,
        occurred_at=ticket.occurred_at,
        request={"batch": "rollback"},
    )
    assert retry.status == "RUNNING" and retry.token is None
    store.fail(ticket, "INVALID_RESULT")


@pytest.mark.parametrize("migration_index", range(MIGRATION_VERSION))
def test_applied_migration_checksum_cannot_be_changed(store, tmp_path, migration_index):
    from worker.store import MIGRATION_FILES

    original = MIGRATION_FILES[migration_index]
    changed = tmp_path / original.name
    changed.write_bytes(original.read_bytes() + b"\n-- altered migration\n")
    with pytest.raises(ValueError, match="checksum"):
        apply_migration(os.environ["C_COMPUTE_TEST_DATABASE_URL"], changed)


def test_all_forward_migrations_are_ready(store):
    assert store.ready()
    with psycopg.connect(os.environ["C_COMPUTE_TEST_DATABASE_URL"]) as conn:
        versions = conn.execute(
            "SELECT version FROM c_compute.schema_version ORDER BY version"
        ).fetchall()
    assert versions == [(version,) for version in range(1, MIGRATION_VERSION + 1)]
