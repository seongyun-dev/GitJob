"""PostgreSQL integration checks; never target an implicit/shared database."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest

from worker.store import (
    MIGRATION_VERSION,
    Artifact,
    ComputeStore,
    IdempotencyConflict,
    LeaseLost,
    StoredMatchingIntegrityError,
    apply_migration,
    digest,
)


def test_user_result_staleness_is_inferred_without_mutating_immutable_row():
    payload = {"current_job_ids": ["SARAMIN:1"]}
    row = {
        "result_id": "ur-" + "1" * 64,
        "user_id": "123",
        "target_key": "target-a",
        "evidence_version": "evidence/v1",
        "projection_version_id": "jp-" + "1" * 64,
        "current_projection_version_id": "jp-" + "2" * 64,
        "compute_contract_version": "contract/v1",
        "status": "READY",
        "recommendation_snapshot_id": "c-" + "3" * 64,
        "compact_payload": payload,
        "payload_hash": digest(payload),
        "created_at": datetime.now(UTC),
    }

    restored = ComputeStore._restore_user_result(row, compare_projection=True)

    assert restored["status"] == "STALE"
    assert restored["recompute_required"] is True
    assert row["status"] == "READY"


def test_projection_selector_pins_the_head_version(monkeypatch):
    store = ComputeStore("postgresql://unused")
    observed_at = datetime(2026, 9, 20, tzinfo=UTC)
    projection_id = "jp-" + "a" * 64
    selected = object()
    selector = SimpleNamespace(criteria_at=lambda value: selected)
    calls = []
    monkeypatch.setattr(
        store,
        "get_job_projection_head",
        lambda: {
            "projection_version_id": projection_id,
            "observed_at": observed_at,
        },
    )
    monkeypatch.setattr(
        store,
        "query_job_projection_demand",
        lambda criteria, *, projection_version_id: calls.append(
            (criteria, projection_version_id)
        )
        or "result",
    )

    assert store.resolve_job_projection_selector(selector) == (selected, "result")
    assert calls == [(selected, projection_id)]


def test_legacy_user_result_is_not_stale_when_projection_comparison_is_disabled():
    payload = {"current_job_ids": []}
    row = {
        "result_id": "ur-" + "1" * 64,
        "user_id": "123",
        "target_key": "target-a",
        "evidence_version": "evidence/v1",
        "projection_version_id": None,
        "current_projection_version_id": "jp-" + "2" * 64,
        "compute_contract_version": "contract/v1",
        "status": "READY",
        "recommendation_snapshot_id": "c-" + "3" * 64,
        "compact_payload": payload,
        "payload_hash": digest(payload),
        "created_at": datetime.now(UTC),
    }

    restored = ComputeStore._restore_user_result(row, compare_projection=False)

    assert restored["status"] == "LEGACY"
    assert restored["recompute_required"] is False


def test_user_result_rejects_compact_payload_hash_mismatch():
    row = {
        "result_id": "ur-" + "1" * 64,
        "user_id": "123",
        "target_key": "target-a",
        "evidence_version": "evidence/v1",
        "projection_version_id": None,
        "current_projection_version_id": None,
        "compute_contract_version": "contract/v1",
        "status": "READY",
        "recommendation_snapshot_id": "c-" + "3" * 64,
        "compact_payload": {"changed": True},
        "payload_hash": digest({"changed": False}),
        "created_at": datetime.now(UTC),
    }

    with pytest.raises(StoredMatchingIntegrityError):
        ComputeStore._restore_user_result(row)


@pytest.mark.parametrize(
    "payload",
    [
        {"current_job_ids": None},
        {"current_job_ids": "SARAMIN:1"},
        {"current_job_ids": ["SARAMIN:1", 2]},
        {"current_job_ids": {"job_id": "SARAMIN:1"}},
    ],
)
def test_matching_page_rejects_malformed_current_job_ids(payload):
    with pytest.raises(StoredMatchingIntegrityError, match="array of strings"):
        ComputeStore._read_current_job_ids(payload)


def test_matching_page_distinguishes_missing_and_valid_current_job_ids():
    assert ComputeStore._read_current_job_ids({"other": True}) == (False, None)
    assert ComputeStore._read_current_job_ids({"current_job_ids": []}) == (True, [])


def test_legacy_current_job_ids_distinguishes_missing_key_from_explicit_null():
    assert (
        ComputeStore._legacy_current_job_ids_payload(
            {"has_current_job_ids": False, "current_job_ids": None}
        )
        is None
    )
    explicit_null = ComputeStore._legacy_current_job_ids_payload(
        {"has_current_job_ids": True, "current_job_ids": None}
    )
    with pytest.raises(StoredMatchingIntegrityError, match="array of strings"):
        ComputeStore._read_current_job_ids(explicit_null)


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


def test_unsettled_ticket_is_reclaimed_when_its_request_content_changes(store):
    """A FAILED ticket has published nothing, so new content may re-run it.

    This is the recovery path for the weekly TREND ticket that a registry
    rollout stranded: it had been FAILED for twelve attempts and every later
    claim computed a different request_hash, so it could never be picked up
    again (S15P21E102-283). No row is deleted and no hash is edited by hand.
    """

    ticket = claim(store, body={"analysis_id": "a1"})
    store.fail(ticket, "SOMETHING_TRANSIENT")

    reclaimed = claim(
        store, ticket.event_id, at=ticket.occurred_at, body={"analysis_id": "moved"}
    )
    assert reclaimed.token is not None
    assert reclaimed.attempt == ticket.attempt + 1

    # The stored hash follows the content that actually ran, so the next
    # attempt with the same content is an ordinary retry rather than a repeat
    # of the same conflict.
    store.fail(reclaimed, "AGAIN")
    again = claim(
        store, ticket.event_id, at=ticket.occurred_at, body={"analysis_id": "moved"}
    )
    assert again.token is not None
    assert again.attempt == reclaimed.attempt + 1


def test_completed_ticket_still_conflicts_when_content_changes(store):
    """The guarantee that matters is kept: no caller is handed foreign results."""

    ticket = claim(store, body={"analysis_id": "a1"})
    store.complete(ticket, [artifact()])
    with pytest.raises(IdempotencyConflict):
        claim(
            store, ticket.event_id, at=ticket.occurred_at, body={"analysis_id": "other"}
        )


def test_scope_change_conflicts_even_on_an_unsettled_ticket(store):
    """Relaxing content never relaxes identity: kind and owner still bind."""

    ticket = claim(store, body={"analysis_id": "a1"})
    store.fail(ticket, "SOMETHING_TRANSIENT")
    with pytest.raises(IdempotencyConflict):
        store.claim(
            event_id=ticket.event_id,
            kind="ANALYSIS",
            owner="456",
            occurred_at=ticket.occurred_at,
            request={"analysis_id": "a1"},
        )


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


def test_job_head_pair_requires_both_results_from_the_same_completion(store):
    stream = str(uuid4())
    first = store.claim(
        event_id=str(uuid4()),
        kind="JOB_BATCH",
        owner=None,
        occurred_at=datetime.now(UTC),
        request={"batch": "first"},
    )
    first_refs = store.complete(
        first,
        [
            Artifact("COHORT", None, {"cohort": "first"}, stream),
            Artifact("DEMAND", None, {"demand": "first"}, stream),
        ],
    )
    assert store.get_job_head_pair(stream) == {
        "event_id": first.event_id,
        "cohort_snapshot_id": first_refs[0]["snapshot_id"],
        "demand_snapshot_id": first_refs[1]["snapshot_id"],
    }

    second = store.claim(
        event_id=str(uuid4()),
        kind="JOB_BATCH",
        owner=None,
        occurred_at=datetime.now(UTC) + timedelta(seconds=1),
        request={"batch": "second"},
    )
    store.complete(
        second,
        [
            Artifact("COHORT", None, {"cohort": "second"}, stream),
            Artifact("DEMAND", None, {"demand": "second"}, stream),
        ],
    )
    with psycopg.connect(os.environ["C_COMPUTE_TEST_DATABASE_URL"]) as conn:
        conn.execute(
            """UPDATE c_compute.head SET snapshot_id = %s, event_id = %s
               WHERE kind = 'COHORT' AND owner = '' AND stream = %s""",
            (first_refs[0]["snapshot_id"], first.event_id, stream),
        )
    assert store.get_job_head_pair(stream) is None


def test_head_snapshot_read_returns_payload_and_lineage_without_writes(store):
    stream = str(uuid4())
    ticket = store.claim(
        event_id=str(uuid4()),
        kind="TREND",
        owner=None,
        occurred_at=datetime.now(UTC),
        request={"trend": "weekly"},
    )
    payload = {"tech_id": "python", "status": "READY"}
    reference = store.complete(ticket, [Artifact("TREND", None, payload, stream)])[0]

    before = store.get_head("TREND", None, stream)
    resolved = store.get_head_snapshot("TREND", None, stream)
    after = store.get_head("TREND", None, stream)

    assert before == after == reference["snapshot_id"]
    assert resolved["snapshot_id"] == reference["snapshot_id"]
    assert resolved["event_id"] == ticket.event_id
    assert resolved["payload"] == payload


def test_bulk_head_payload_read_and_period_compatible_public_selection(store):
    now = datetime.now(UTC)

    def publish_public(
        event_id, stream, period_start, period_end, at, *, target_period=None
    ):
        ticket = store.claim(
            event_id=event_id,
            kind="PUBLIC_REPO",
            owner=None,
            occurred_at=at,
            request={"snapshot": event_id},
        )
        payload = {
            "result": {
                "registry_version": "registry-test",
                "include_partial": False,
                "records": [
                    {
                        "included_in_denominator": True,
                        "target_period": target_period,
                        "activity_period_start": period_start,
                        "activity_period_end": period_end,
                    }
                ],
            }
        }
        row = Artifact("PUBLIC_GITHUB", None, payload, stream)
        reference = store.complete(ticket, [row])[0]
        return reference["snapshot_id"], payload

    publish_public(
        str(uuid4()),
        str(uuid4()),
        "2026-08-01",
        "2026-08-31",
        now,
        target_period="2026-08-01/2026-08-31",
    )
    publish_public(
        str(uuid4()),
        str(uuid4()),
        "2026-09-01",
        "2026-09-30",
        now + timedelta(seconds=1),
    )
    # S15P21E102-337: a WEEK observation no longer accepts the August MONTH
    # PUBLIC that merely contains it. The week-specific PUBLIC below is what
    # qualifies now.
    assert (
        store.select_public_snapshot(
            registry_version="registry-test",
            include_partial=False,
            week_start="2026-08-24",
        )
        is None
    )
    week_id, week_payload = publish_public(
        str(uuid4()),
        str(uuid4()),
        "2026-08-24",
        "2026-08-30",
        now + timedelta(seconds=2),
        target_period="2026-08-24/2026-08-30",
    )
    assert store.select_public_snapshot(
        registry_version="registry-test",
        include_partial=False,
        week_start="2026-08-24",
    ) == (week_id, week_payload)

    trend_ticket = store.claim(
        event_id=str(uuid4()),
        kind="TREND",
        owner=None,
        occurred_at=now,
        request={"week": "2026-08-24"},
    )
    stream = str(uuid4())
    payload = {"tech_id": "python", "points": []}
    store.complete(trend_ticket, [Artifact("TREND", None, payload, stream)])
    assert store.get_head_payloads(
        kind="TREND", owner=None, streams=(stream, str(uuid4()))
    ) == {stream: payload}
    resolved = store.get_head_snapshots(
        kind="TREND", owner=None, streams=(stream, str(uuid4()))
    )
    assert set(resolved) == {stream}
    assert resolved[stream]["payload"] == payload
    assert resolved[stream]["event_id"] == trend_ticket.event_id


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
