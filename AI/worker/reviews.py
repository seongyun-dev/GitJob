"""Transactional PostgreSQL persistence for Registry mapping reviews."""

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from registry.mapper import MatchStatus, RegistryMapper
from registry.review import (
    DecisionKind,
    ReviewRecord,
    ReviewStatus,
    legacy_review_ids,
    legacy_review_source_identity,
    reprocess_record,
    resolve_record,
    review_source_digest,
    same_legacy_review_source,
)

REVIEW_MIGRATION_FILE = (
    Path(__file__).resolve().parents[2]
    / "BE/src/main/resources/db/c-compute/003_registry_review.sql"
)


class ReviewNotFound(LookupError):
    """The requested review or cohort snapshot does not exist."""


class ReviewVersionConflict(ValueError):
    """The caller's optimistic review version is stale."""


class ReviewIdempotencyConflict(ValueError):
    """An immutable review ID or action key was reused with different content."""


class ReviewStateConflict(ValueError):
    """The requested transition is not valid for the current review state."""


class StoredReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record: ReviewRecord
    version: int = Field(ge=1)
    cohort_snapshot_ids: tuple[str, ...]


class ReviewPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[StoredReview, ...]
    next_cursor: str | None


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _assert_current_source(
    persisted: Mapping[str, Any], record: ReviewRecord, source_hash: str
) -> None:
    if (
        persisted["source_dataset_snapshot_id"] != record.source_dataset_snapshot_id
        or persisted["source_hash"] != source_hash
    ):
        raise ReviewIdempotencyConflict(
            "review ID already has different immutable source provenance"
        )


def _is_same_legacy_source(persisted: Mapping[str, Any], record: ReviewRecord) -> bool:
    try:
        historical = ReviewRecord.model_validate(persisted["record"])
    except ValueError:
        return False
    historical_source = {
        "review_id": historical.review_id,
        **legacy_review_source_identity(historical),
    }
    return persisted["source_hash"] == _digest(
        historical_source
    ) and same_legacy_review_source(historical, record)


def _coerce_initial_record(value: ReviewRecord | Mapping[str, Any]) -> ReviewRecord:
    record = (
        value if isinstance(value, ReviewRecord) else ReviewRecord.model_validate(value)
    )
    if record.review_id_version != "registry-review-id/v3":
        raise ValueError("database review ingestion requires v3 source identity")
    if not record.source_dataset_snapshot_id:
        raise ValueError("database review requires source_dataset_snapshot_id")
    if record.review_id != "review-" + review_source_digest(record)[:24]:
        raise ReviewIdempotencyConflict(
            "review ID does not match immutable source provenance"
        )
    if (
        record.original_match_status is MatchStatus.MATCHED
        or record.status is not ReviewStatus.PENDING
        or record.resolved_tech_id is not None
        or len(record.attempts) != 1
        or record.attempts[0].decision_kind is not DecisionKind.AUTOMATIC
    ):
        raise ValueError(
            "database review ingestion requires one unresolved initial attempt"
        )
    return record


def _validate_nonempty(value: str, name: str, *, maximum: int | None = None) -> str:
    if not value or not value.strip() or (maximum is not None and len(value) > maximum):
        raise ValueError(f"invalid {name}")
    return value


def _load_cohorts(
    conn: Connection[Any], review_ids: list[str]
) -> dict[str, tuple[str, ...]]:
    if not review_ids:
        return {}
    with conn.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            """SELECT review_id, cohort_snapshot_id
               FROM c_compute.registry_review_cohort
               WHERE review_id = ANY(%s)
               ORDER BY review_id, cohort_snapshot_id""",
            (review_ids,),
        ).fetchall()
    result: dict[str, list[str]] = {review_id: [] for review_id in review_ids}
    for row in rows:
        result[row["review_id"]].append(row["cohort_snapshot_id"])
    return {review_id: tuple(values) for review_id, values in result.items()}


def _stored_from_rows(
    conn: Connection[Any], rows: list[dict[str, Any]]
) -> tuple[StoredReview, ...]:
    cohort_ids = _load_cohorts(conn, [row["review_id"] for row in rows])
    return tuple(
        StoredReview(
            record=ReviewRecord.model_validate(row["record"]),
            version=row["version"],
            cohort_snapshot_ids=cohort_ids[row["review_id"]],
        )
        for row in rows
    )


def insert_reviews(
    conn: Connection[Any],
    records: Iterable[ReviewRecord | Mapping[str, Any]],
    cohort_snapshot_id: str,
) -> tuple[str, ...]:
    """Insert immutable review sources and cohort links in the caller's transaction."""
    _validate_nonempty(cohort_snapshot_id, "cohort_snapshot_id", maximum=66)
    prepared = tuple(_coerce_initial_record(value) for value in records)
    if not prepared:
        return ()
    source_hashes: dict[str, str] = {}
    for record in prepared:
        source_hash = review_source_digest(record)
        existing_hash = source_hashes.get(record.review_id)
        if existing_hash is not None and existing_hash != source_hash:
            raise ReviewIdempotencyConflict(
                "review ID has multiple immutable source variants in one batch"
            )
        source_hashes[record.review_id] = source_hash

    candidate_ids = sorted(
        {
            candidate
            for record in prepared
            for candidate in (record.review_id, *legacy_review_ids(record))
        }
    )
    with conn.cursor(row_factory=dict_row) as cursor:
        cohort = cursor.execute(
            "SELECT kind FROM c_compute.snapshot WHERE snapshot_id = %s FOR SHARE",
            (cohort_snapshot_id,),
        ).fetchone()
        if cohort is None:
            raise ReviewNotFound(f"cohort snapshot not found: {cohort_snapshot_id}")
        if cohort["kind"] != "COHORT":
            raise ValueError("review cohort reference must identify a COHORT snapshot")
        existing_rows = cursor.execute(
            """SELECT review_id, source_dataset_snapshot_id, source_hash, record
               FROM c_compute.registry_review
               WHERE review_id = ANY(%s) FOR SHARE""",
            (candidate_ids,),
        ).fetchall()
        existing = {row["review_id"]: row for row in existing_rows}

        target_ids = []
        new_records: dict[str, ReviewRecord] = {}
        for record in prepared:
            current = existing.get(record.review_id)
            if current is not None:
                _assert_current_source(current, record, source_hashes[record.review_id])
                target_ids.append(record.review_id)
                continue
            target = next(
                (
                    legacy_id
                    for legacy_id in legacy_review_ids(record)
                    if legacy_id in existing
                    and _is_same_legacy_source(existing[legacy_id], record)
                ),
                None,
            )
            if target is not None:
                target_ids.append(target)
                continue
            duplicate = new_records.get(record.review_id)
            if duplicate is None:
                new_records[record.review_id] = record
            target_ids.append(record.review_id)

        cursor.executemany(
            """INSERT INTO c_compute.registry_review
               (review_id, source_dataset_snapshot_id, source_hash, record, status)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (review_id) DO NOTHING""",
            [
                (
                    record.review_id,
                    record.source_dataset_snapshot_id,
                    source_hashes[record.review_id],
                    Jsonb(record.model_dump(mode="json")),
                    record.status.value,
                )
                for record in new_records.values()
            ],
        )
        persisted_rows = cursor.execute(
            """SELECT review_id, source_dataset_snapshot_id, source_hash, record
               FROM c_compute.registry_review
               WHERE review_id = ANY(%s) FOR SHARE""",
            (sorted(set(target_ids)),),
        ).fetchall()
        persisted = {row["review_id"]: row for row in persisted_rows}
        for record, target_id in zip(prepared, target_ids, strict=True):
            row = persisted.get(target_id)
            if row is None:
                raise ReviewIdempotencyConflict("review insert did not persist")
            if target_id == record.review_id:
                _assert_current_source(row, record, source_hashes[record.review_id])
            elif not _is_same_legacy_source(row, record):
                raise ReviewIdempotencyConflict(
                    "legacy review ID has different immutable source provenance"
                )
        cursor.executemany(
            """INSERT INTO c_compute.registry_review_cohort
               (review_id, cohort_snapshot_id) VALUES (%s, %s)
               ON CONFLICT DO NOTHING""",
            [(review_id, cohort_snapshot_id) for review_id in sorted(set(target_ids))],
        )
    return tuple(target_ids)


def get_review(conn: Connection[Any], review_id: str) -> StoredReview:
    _validate_nonempty(review_id, "review_id", maximum=31)
    with conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            """SELECT review_id, record, version
               FROM c_compute.registry_review WHERE review_id = %s""",
            (review_id,),
        ).fetchone()
    if row is None:
        raise ReviewNotFound(f"review not found: {review_id}")
    return _stored_from_rows(conn, [row])[0]


def query_reviews(
    conn: Connection[Any],
    *,
    status: ReviewStatus | str | None = None,
    after: str | None = None,
    limit: int = 50,
) -> ReviewPage:
    if not 1 <= limit <= 100:
        raise ValueError("review page limit must be between 1 and 100")
    parsed_status = ReviewStatus(status) if status is not None else None
    if after is not None:
        _validate_nonempty(after, "review cursor", maximum=31)
    predicates = []
    parameters: list[Any] = []
    if parsed_status is not None:
        predicates.append("status = %s")
        parameters.append(parsed_status.value)
    if after is not None:
        predicates.append("review_id > %s")
        parameters.append(after)
    where = " WHERE " + " AND ".join(predicates) if predicates else ""
    parameters.append(limit + 1)
    with conn.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            "SELECT review_id, record, version "
            "FROM c_compute.registry_review"
            f"{where} ORDER BY review_id LIMIT %s",
            parameters,
        ).fetchall()
    has_next = len(rows) > limit
    page_rows = rows[:limit]
    items = _stored_from_rows(conn, page_rows)
    return ReviewPage(
        items=items,
        next_cursor=items[-1].record.review_id if has_next else None,
    )


def _locked_row(conn: Connection[Any], review_id: str) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            """SELECT review_id, record, version
               FROM c_compute.registry_review
               WHERE review_id = %s FOR UPDATE""",
            (review_id,),
        ).fetchone()
    if row is None:
        raise ReviewNotFound(f"review not found: {review_id}")
    return row


def _check_replay(
    conn: Connection[Any],
    *,
    review_id: str,
    idempotency_key: str,
    request_hash: str,
) -> StoredReview | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        action = cursor.execute(
            """SELECT request_hash FROM c_compute.registry_review_action
               WHERE review_id = %s AND idempotency_key = %s""",
            (review_id, idempotency_key),
        ).fetchone()
    if action is None:
        return None
    if action["request_hash"] != request_hash:
        raise ReviewIdempotencyConflict(
            "review action idempotency key already has different content"
        )
    return get_review(conn, review_id)


def _update_review(
    conn: Connection[Any],
    *,
    previous: dict[str, Any],
    updated: ReviewRecord,
    action: str,
    actor: str,
    note: str,
    registry_version: str,
    idempotency_key: str,
    request_hash: str,
) -> StoredReview:
    before_version = previous["version"]
    after_version = before_version + 1
    with conn.cursor(row_factory=dict_row) as cursor:
        changed = cursor.execute(
            """UPDATE c_compute.registry_review
               SET record = %s, status = %s, version = %s,
                   updated_at = clock_timestamp()
               WHERE review_id = %s AND version = %s""",
            (
                Jsonb(updated.model_dump(mode="json")),
                updated.status.value,
                after_version,
                updated.review_id,
                before_version,
            ),
        )
        if changed.rowcount != 1:
            raise ReviewVersionConflict("review version changed during update")
        cursor.execute(
            """INSERT INTO c_compute.registry_review_action
               (review_id, idempotency_key, request_hash, action, actor, note,
                registry_version, before_version, after_version)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                updated.review_id,
                idempotency_key,
                request_hash,
                action,
                actor,
                note,
                registry_version,
                before_version,
                after_version,
            ),
        )
    return get_review(conn, updated.review_id)


def _mutation_inputs(
    *,
    review_id: str,
    actor: str,
    note: str,
    idempotency_key: str,
    expected_version: int,
    now: datetime | None,
) -> datetime:
    _validate_nonempty(review_id, "review_id", maximum=31)
    _validate_nonempty(actor, "review actor", maximum=128)
    _validate_nonempty(note, "review note")
    _validate_nonempty(idempotency_key, "idempotency_key", maximum=128)
    if expected_version < 1:
        raise ValueError("expected review version must be positive")
    attempted_at = now or datetime.now(UTC)
    if attempted_at.tzinfo is None:
        raise ValueError("review attempt timestamp needs a timezone")
    return attempted_at


def resolve_review(
    conn: Connection[Any],
    *,
    review_id: str,
    tech_id: str,
    actor: str,
    note: str,
    mapper: RegistryMapper,
    idempotency_key: str,
    expected_version: int,
    now: datetime | None = None,
) -> StoredReview:
    """Record an explicit human decision against an active approved Registry."""
    attempted_at = _mutation_inputs(
        review_id=review_id,
        actor=actor,
        note=note,
        idempotency_key=idempotency_key,
        expected_version=expected_version,
        now=now,
    )
    _validate_nonempty(tech_id, "tech_id")
    request_hash = _digest(
        {
            "action": "MANUAL_RESOLVE",
            "review_id": review_id,
            "tech_id": tech_id,
            "actor": actor,
            "note": note,
            "registry_version": mapper.registry_version,
            "expected_version": expected_version,
        }
    )
    row = _locked_row(conn, review_id)
    replay = _check_replay(
        conn,
        review_id=review_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if replay is not None:
        return replay
    if row["version"] != expected_version:
        raise ReviewVersionConflict("review version does not match expected_version")
    record = ReviewRecord.model_validate(row["record"])
    updated = resolve_record(
        record,
        tech_id=tech_id,
        reviewer=actor,
        note=note,
        mapper=mapper,
        attempted_at=attempted_at,
    )
    return _update_review(
        conn,
        previous=row,
        updated=updated,
        action="MANUAL_RESOLVE",
        actor=actor,
        note=note,
        registry_version=mapper.registry_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )


def reprocess_review(
    conn: Connection[Any],
    *,
    review_id: str,
    mapper: RegistryMapper,
    actor: str,
    note: str,
    idempotency_key: str,
    expected_version: int,
    now: datetime | None = None,
) -> StoredReview:
    """Explicitly re-run one pending record with the supplied approved Registry."""
    attempted_at = _mutation_inputs(
        review_id=review_id,
        actor=actor,
        note=note,
        idempotency_key=idempotency_key,
        expected_version=expected_version,
        now=now,
    )
    request_hash = _digest(
        {
            "action": "REPROCESS",
            "review_id": review_id,
            "actor": actor,
            "note": note,
            "registry_version": mapper.registry_version,
            "expected_version": expected_version,
        }
    )
    row = _locked_row(conn, review_id)
    replay = _check_replay(
        conn,
        review_id=review_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if replay is not None:
        return replay
    if row["version"] != expected_version:
        raise ReviewVersionConflict("review version does not match expected_version")
    record = ReviewRecord.model_validate(row["record"])
    if record.status is not ReviewStatus.PENDING:
        raise ReviewStateConflict("only a pending review can be reprocessed")

    updated = reprocess_record(
        record,
        mapper,
        attempted_at=attempted_at,
        reviewer=actor,
        note=note,
    )
    return _update_review(
        conn,
        previous=row,
        updated=updated,
        action="REPROCESS",
        actor=actor,
        note=note,
        registry_version=mapper.registry_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
