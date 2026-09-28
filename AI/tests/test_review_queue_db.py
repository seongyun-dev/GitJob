"""PostgreSQL review-queue checks for S15P21E102-88."""

import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from job.classifier import classify_job_batch
from job.contracts import JobAnalysisInputBatch
from registry.contracts import TechnologyRegistry, load_registry
from registry.mapper import MatchStatus, RegistryMapper
from registry.review import (
    DecisionKind,
    ReviewStatus,
    build_records,
    legacy_review_ids,
    resolve_record,
)
from worker.reviews import (
    REVIEW_MIGRATION_FILE,
    ReviewIdempotencyConflict,
    ReviewNotFound,
    ReviewStateConflict,
    ReviewVersionConflict,
    get_review,
    insert_reviews,
    query_reviews,
    reprocess_review,
    resolve_review,
)
from worker.store import apply_migration

AI_ROOT = Path(__file__).resolve().parents[1]
JOB_FIXTURE = AI_ROOT / "job" / "fixtures" / "job_analysis_input_v1.json"
REGISTRY_PATH = AI_ROOT / "registry" / "data" / "technology_registry_v1.json"


def base_registry() -> TechnologyRegistry:
    return load_registry(REGISTRY_PATH, repository_root=AI_ROOT.parent)


def registry_with_quantumdb() -> TechnologyRegistry:
    payload = base_registry().model_dump(mode="json")
    payload["registry_version"] = "registry-20260908.1"
    payload["technologies"] = (
        *payload["technologies"],
        {
            "tech_id": "quantumdb",
            "display_name": "QuantumDB",
            "categories": ["AI_DATA"],
            "status": "ACTIVE",
            "provenance_refs": ["https://example.com/quantumdb"],
        },
    )
    payload["mappings"] = (
        *payload["mappings"],
        {
            "tech_id": "quantumdb",
            "mapping_type": "ALIAS",
            "ecosystem": None,
            "value": "QuantumDB",
            "match_mode": "EXACT",
            "status": "ACTIVE",
            "provenance_refs": ["https://example.com/quantumdb"],
        },
    )
    return TechnologyRegistry.model_validate_json(json.dumps(payload))


def classified_batch():
    payload = json.loads(JOB_FIXTURE.read_text(encoding="utf-8"))
    payload["dataset_snapshot_id"] = f"review-test-{uuid4()}"
    batch = JobAnalysisInputBatch.model_validate(payload)
    return classify_job_batch(batch, RegistryMapper(base_registry()))


def quantumdb_record():
    return next(
        record
        for record in build_records(classified_batch())
        if record.raw_technology == "QuantumDB"
    )


@pytest.fixture
def review_conn():
    dsn = os.getenv("C_COMPUTE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set C_COMPUTE_TEST_DATABASE_URL to an isolated PostgreSQL test DB")
    apply_migration(dsn)
    apply_migration(dsn, REVIEW_MIGRATION_FILE)
    conn = psycopg.connect(dsn)
    conn.execute("BEGIN")
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def add_cohort_snapshot(conn, suffix: str | None = None) -> str:
    snapshot_id = f"c-{suffix or uuid4().hex}"
    conn.execute(
        """INSERT INTO c_compute.snapshot(snapshot_id, kind, owner, payload)
           VALUES (%s, 'COHORT', '', %s)""",
        (snapshot_id, json.dumps({"test": snapshot_id})),
    )
    return snapshot_id


def test_build_records_is_pure_and_uses_source_collection_time() -> None:
    batch = classified_batch()

    records = build_records(batch)

    assert len(records) == 4
    assert all(
        record.source_dataset_snapshot_id == batch.dataset_snapshot_id
        for record in records
    )
    source_times = {row.source_record_id: row.collected_at for row in batch.records}
    assert all(
        record.attempts[0].attempted_at == source_times[record.source_record_id]
        for record in records
    )
    assert {record.original_match_status for record in records} == {
        MatchStatus.UNKNOWN,
        MatchStatus.AMBIGUOUS,
    }


def test_insert_is_idempotent_and_links_one_review_to_multiple_cohorts(
    review_conn,
) -> None:
    record = quantumdb_record()
    first_cohort = add_cohort_snapshot(review_conn)
    second_cohort = add_cohort_snapshot(review_conn)

    assert insert_reviews(
        review_conn, [record.model_dump(mode="json")], first_cohort
    ) == (record.review_id,)
    insert_reviews(review_conn, [record], first_cohort)
    insert_reviews(review_conn, [record], second_cohort)

    stored = get_review(review_conn, record.review_id)
    assert stored.version == 1
    assert stored.record == record
    assert stored.cohort_snapshot_ids == tuple(sorted((first_cohort, second_cohort)))
    persisted_hash = review_conn.execute(
        "SELECT source_hash FROM c_compute.registry_review WHERE review_id = %s",
        (record.review_id,),
    ).fetchone()[0]
    assert record.review_id == "review-" + persisted_hash[:24]
    assert (
        review_conn.execute(
            "SELECT count(*) FROM c_compute.registry_review WHERE review_id = %s",
            (record.review_id,),
        ).fetchone()[0]
        == 1
    )


def test_insert_rejects_same_id_with_changed_immutable_source(review_conn) -> None:
    record = quantumdb_record()
    cohort = add_cohort_snapshot(review_conn)
    insert_reviews(review_conn, [record], cohort)
    changed = record.model_copy(update={"evidence_text": "replaced source evidence"})

    with pytest.raises(ReviewIdempotencyConflict, match="immutable"):
        insert_reviews(review_conn, [changed], cohort)


def test_v3_replay_links_existing_v2_resolution_without_reopening_it(
    review_conn,
) -> None:
    record = quantumdb_record()
    cohort = add_cohort_snapshot(review_conn)
    legacy_id = legacy_review_ids(record)[0]
    resolved = resolve_record(
        record,
        tech_id="postgresql",
        reviewer="legacy-admin",
        note="기존 수동 결정",
        mapper=RegistryMapper(base_registry()),
        attempted_at=datetime(2026, 9, 9, tzinfo=UTC),
    )
    historical = resolved.model_dump(mode="json")
    historical["review_id"] = legacy_id
    historical.pop("review_id_version")
    historical.pop("char_start")
    historical.pop("char_end")
    immutable = {
        key: historical[key]
        for key in (
            "review_id",
            "source_dataset_snapshot_id",
            "mention_index",
            "source_record_id",
            "source_site",
            "source_url",
            "source_surface",
            "raw_technology",
            "context",
            "evidence_section",
            "evidence_text",
        )
    }
    source_hash = sha256(
        json.dumps(
            immutable,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    review_conn.execute(
        """INSERT INTO c_compute.registry_review
           (review_id, source_dataset_snapshot_id, source_hash, record, status, version)
           VALUES (%s, %s, %s, %s, 'RESOLVED', 2)""",
        (
            legacy_id,
            record.source_dataset_snapshot_id,
            source_hash,
            Jsonb(historical),
        ),
    )
    review_conn.execute(
        """INSERT INTO c_compute.registry_review_action
           (review_id, idempotency_key, request_hash, action, actor, note,
            registry_version, before_version, after_version)
           VALUES (%s, 'legacy-resolution', %s, 'MANUAL_RESOLVE',
                   'legacy-admin', '기존 수동 결정', %s, 1, 2)""",
        (legacy_id, "f" * 64, base_registry().registry_version),
    )

    assert insert_reviews(review_conn, [record], cohort) == (legacy_id,)

    stored = get_review(review_conn, legacy_id)
    assert stored.record.status is ReviewStatus.RESOLVED
    assert stored.record.resolved_tech_id == "postgresql"
    assert stored.cohort_snapshot_ids == (cohort,)
    assert (
        review_conn.execute(
            "SELECT count(*) FROM c_compute.registry_review "
            "WHERE source_dataset_snapshot_id = %s",
            (record.source_dataset_snapshot_id,),
        ).fetchone()[0]
        == 1
    )
    assert (
        review_conn.execute(
            "SELECT count(*) FROM c_compute.registry_review_action "
            "WHERE review_id = %s",
            (legacy_id,),
        ).fetchone()[0]
        == 1
    )


def test_bulk_review_insert_has_bounded_client_statement_count(review_conn) -> None:
    payload = json.loads(JOB_FIXTURE.read_text(encoding="utf-8"))
    template = payload["records"][3]
    payload["records"] = []
    for index in range(100):
        item = json.loads(json.dumps(template))
        item["source_record_id"] = f"bulk-{index}"
        item["source_posting_id"] = f"bulk-{index}"
        item["source_url"] = f"https://example.invalid/jobs/bulk-{index}"
        item["title"] = f"데이터 엔지니어 {index}"
        payload["records"].append(item)
    records = build_records(
        classify_job_batch(
            JobAnalysisInputBatch.model_validate_json(json.dumps(payload)),
            RegistryMapper(base_registry()),
        )
    )
    cohort = add_cohort_snapshot(review_conn)
    calls = {"execute": 0, "executemany": 0}

    class CursorProxy:
        def __init__(self, cursor):
            self.cursor = cursor

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.cursor.close()
            return False

        def execute(self, *args, **kwargs):
            calls["execute"] += 1
            return self.cursor.execute(*args, **kwargs)

        def executemany(self, *args, **kwargs):
            calls["executemany"] += 1
            return self.cursor.executemany(*args, **kwargs)

    class ConnectionProxy:
        def cursor(self, *args, **kwargs):
            return CursorProxy(review_conn.cursor(*args, **kwargs))

    insert_reviews(ConnectionProxy(), records, cohort)

    assert len(records) == 100
    assert calls == {"execute": 3, "executemany": 2}


def test_query_has_stable_keyset_pagination_and_status_filter(review_conn) -> None:
    records = build_records(classified_batch())
    cohort = add_cohort_snapshot(review_conn)
    insert_reviews(review_conn, records, cohort)

    ids = []
    after = None
    while True:
        page = query_reviews(
            review_conn,
            status=ReviewStatus.PENDING,
            after=after,
            limit=2,
        )
        ids.extend(item.record.review_id for item in page.items)
        if page.next_cursor is None:
            break
        assert page.next_cursor == page.items[-1].record.review_id
        after = page.next_cursor

    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))
    assert {record.review_id for record in records} <= set(ids)


def test_manual_resolution_validates_registry_and_records_audit(review_conn) -> None:
    record = quantumdb_record()
    cohort = add_cohort_snapshot(review_conn)
    insert_reviews(review_conn, [record], cohort)
    mapper = RegistryMapper(base_registry())
    decided_at = datetime(2026, 9, 8, 1, 2, 3, tzinfo=UTC)

    resolved = resolve_review(
        review_conn,
        review_id=record.review_id,
        tech_id="postgresql",
        actor="reviewer-123",
        note="원문 확인 후 PostgreSQL로 결정",
        mapper=mapper,
        idempotency_key="manual-1",
        expected_version=1,
        now=decided_at,
    )

    assert resolved.version == 2
    assert resolved.record.status is ReviewStatus.RESOLVED
    assert resolved.record.resolved_tech_id == "postgresql"
    assert resolved.record.attempts[-1].decision_kind is DecisionKind.MANUAL
    assert resolved.record.attempts[-1].reviewer == "reviewer-123"
    assert resolved.record.attempts[-1].note == "원문 확인 후 PostgreSQL로 결정"
    audit = review_conn.execute(
        """SELECT action, actor, note, before_version, after_version
           FROM c_compute.registry_review_action
           WHERE review_id = %s AND idempotency_key = 'manual-1'""",
        (record.review_id,),
    ).fetchone()
    assert audit == (
        "MANUAL_RESOLVE",
        "reviewer-123",
        "원문 확인 후 PostgreSQL로 결정",
        1,
        2,
    )

    replay = resolve_review(
        review_conn,
        review_id=record.review_id,
        tech_id="postgresql",
        actor="reviewer-123",
        note="원문 확인 후 PostgreSQL로 결정",
        mapper=mapper,
        idempotency_key="manual-1",
        expected_version=1,
        now=decided_at,
    )
    assert replay == resolved
    assert len(replay.record.attempts) == 2


def test_manual_resolution_can_correct_prior_decision_and_keeps_both_actions(
    review_conn,
) -> None:
    record = quantumdb_record()
    insert_reviews(review_conn, [record], add_cohort_snapshot(review_conn))
    mapper = RegistryMapper(base_registry())
    first = resolve_review(
        review_conn,
        review_id=record.review_id,
        tech_id="postgresql",
        actor="reviewer-123",
        note="원문 확인 후 최초 결정",
        mapper=mapper,
        idempotency_key="manual-correction-1",
        expected_version=1,
        now=datetime(2026, 9, 8, 1, 2, 3, tzinfo=UTC),
    )

    corrected = resolve_review(
        review_conn,
        review_id=record.review_id,
        tech_id="python",
        actor="reviewer-456",
        note="교차 검토 후 결정 교정",
        mapper=mapper,
        idempotency_key="manual-correction-2",
        expected_version=2,
        now=datetime(2026, 9, 8, 2, 3, 4, tzinfo=UTC),
    )

    assert corrected.version == 3
    assert corrected.record.status is ReviewStatus.RESOLVED
    assert corrected.record.resolved_tech_id == "python"
    assert corrected.record.attempts[:-1] == first.record.attempts
    assert tuple(
        (attempt.tech_id, attempt.reviewer)
        for attempt in corrected.record.attempts[-2:]
    ) == (("postgresql", "reviewer-123"), ("python", "reviewer-456"))
    actions = review_conn.execute(
        """SELECT idempotency_key, before_version, after_version
           FROM c_compute.registry_review_action
           WHERE review_id = %s
           ORDER BY after_version""",
        (record.review_id,),
    ).fetchall()
    assert actions == [
        ("manual-correction-1", 1, 2),
        ("manual-correction-2", 2, 3),
    ]


def test_mutation_reports_missing_version_idempotency_and_inactive_conflicts(
    review_conn,
) -> None:
    record = quantumdb_record()
    cohort = add_cohort_snapshot(review_conn)
    insert_reviews(review_conn, [record], cohort)
    mapper = RegistryMapper(base_registry())

    with pytest.raises(ReviewNotFound):
        resolve_review(
            review_conn,
            review_id="review-missing",
            tech_id="postgresql",
            actor="reviewer",
            note="확인",
            mapper=mapper,
            idempotency_key="missing",
            expected_version=1,
        )
    with pytest.raises(ReviewVersionConflict):
        resolve_review(
            review_conn,
            review_id=record.review_id,
            tech_id="postgresql",
            actor="reviewer",
            note="확인",
            mapper=mapper,
            idempotency_key="wrong-version",
            expected_version=99,
        )
    with pytest.raises(ValueError, match="active Registry tech_id"):
        resolve_review(
            review_conn,
            review_id=record.review_id,
            tech_id="quantumdb",
            actor="reviewer",
            note="아직 Registry 미승인",
            mapper=mapper,
            idempotency_key="inactive",
            expected_version=1,
        )

    resolve_review(
        review_conn,
        review_id=record.review_id,
        tech_id="postgresql",
        actor="reviewer",
        note="확인",
        mapper=mapper,
        idempotency_key="same-key",
        expected_version=1,
    )
    with pytest.raises(ReviewIdempotencyConflict):
        resolve_review(
            review_conn,
            review_id=record.review_id,
            tech_id="python",
            actor="reviewer",
            note="다른 요청",
            mapper=mapper,
            idempotency_key="same-key",
            expected_version=1,
        )


def test_explicit_reprocess_uses_approved_registry_and_preserves_manual_resolution(
    review_conn,
) -> None:
    record = quantumdb_record()
    cohort = add_cohort_snapshot(review_conn)
    insert_reviews(review_conn, [record], cohort)

    reprocessed = reprocess_review(
        review_conn,
        review_id=record.review_id,
        mapper=RegistryMapper(registry_with_quantumdb()),
        actor="operator-7",
        note="승인 Registry 갱신 재처리",
        idempotency_key="reprocess-1",
        expected_version=1,
        now=datetime(2026, 9, 8, 2, 3, 4, tzinfo=UTC),
    )

    assert reprocessed.version == 2
    assert reprocessed.record.status is ReviewStatus.RESOLVED
    assert reprocessed.record.resolved_tech_id == "quantumdb"
    assert reprocessed.record.attempts[-1].decision_kind is DecisionKind.AUTOMATIC
    assert reprocessed.record.attempts[-1].reviewer == "operator-7"
    assert reprocessed.record.attempts[-1].note == "승인 Registry 갱신 재처리"

    with pytest.raises(ReviewStateConflict, match="pending"):
        reprocess_review(
            review_conn,
            review_id=record.review_id,
            mapper=RegistryMapper(registry_with_quantumdb()),
            actor="operator-7",
            note="resolved 결과는 자동으로 덮어쓰지 않음",
            idempotency_key="reprocess-2",
            expected_version=2,
        )

    # A later compute replay only adds cohort provenance; it cannot erase resolution.
    replay_attempt = record.attempts[0].model_copy(
        update={"registry_version": "registry-replay"}
    )
    registry_replay = record.model_copy(
        update={
            "original_match_status": MatchStatus.AMBIGUOUS,
            "candidates": ("postgresql",),
            "attempts": (replay_attempt,),
        }
    )
    insert_reviews(
        review_conn,
        [registry_replay],
        add_cohort_snapshot(review_conn),
    )
    replayed = get_review(review_conn, record.review_id)
    assert replayed.record == reprocessed.record
    assert replayed.version == reprocessed.version
    assert len(replayed.cohort_snapshot_ids) == 2


def test_caller_transaction_rolls_back_review_and_cohort_link(review_conn) -> None:
    record = quantumdb_record()
    cohort = add_cohort_snapshot(review_conn)
    savepoint = f"review_{uuid4().hex}"
    review_conn.execute(f"SAVEPOINT {savepoint}")
    insert_reviews(review_conn, [record], cohort)
    review_conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")

    with pytest.raises(ReviewNotFound):
        get_review(review_conn, record.review_id)
