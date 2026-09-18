"""PostgreSQL snapshots and fenced, retry-safe completion of C compute events."""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

MIGRATION_VERSION = 4
MIGRATION_FILE = (
    Path(__file__).resolve().parents[2]
    / "BE/src/main/resources/db/c-compute/001_c_compute.sql"
)
MIGRATION_FILES = (
    MIGRATION_FILE,
    Path(__file__).resolve().parents[2]
    / "BE/src/main/resources/db/c-compute/002_job_matching_projection.sql",
    Path(__file__).resolve().parents[2]
    / "BE/src/main/resources/db/c-compute/003_registry_review.sql",
    Path(__file__).resolve().parents[2]
    / "BE/src/main/resources/db/c-compute/004_registry_review_source_identity.sql",
)


class IdempotencyConflict(ValueError):
    """The caller reused an event ID for a different immutable request."""


class LeaseLost(RuntimeError):
    """Another attempt owns the event, or this attempt's lease expired."""


class StoredMatchingIntegrityError(RuntimeError):
    """Persisted matching references disagree without exposing stored content."""


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _migration_version(path: Path, index: int) -> int:
    prefix = path.name.split("_", 1)[0]
    return int(prefix) if prefix.isdigit() else index


def apply_migration(dsn: str, path: Path | tuple[Path, ...] | None = None) -> None:
    """Explicit operator action, never run as an application startup side effect."""
    paths = (
        MIGRATION_FILES if path is None else (path,) if isinstance(path, Path) else path
    )
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute("SET LOCAL statement_timeout = '15s'")
        conn.execute("SELECT pg_advisory_xact_lock(331029)")
        for index, migration_path in enumerate(paths, start=1):
            source = migration_path.read_bytes()
            checksum = hashlib.sha256(source.replace(b"\r\n", b"\n")).hexdigest()
            version = _migration_version(migration_path, index)
            exists = conn.execute(
                "SELECT to_regclass('c_compute.schema_version')"
            ).fetchone()[0]
            if exists:
                row = conn.execute(
                    "SELECT checksum FROM c_compute.schema_version WHERE version = %s",
                    (version,),
                ).fetchone()
                if row:
                    if row[0] != checksum:
                        raise ValueError(
                            "C migration checksum mismatch; do not rewrite applied DDL"
                        )
                    continue
            conn.execute(source.decode("utf-8"))
            conn.execute(
                "INSERT INTO c_compute.schema_version(version, checksum) VALUES (%s, %s)",
                (version, checksum),
            )


@dataclass(frozen=True)
class Artifact:
    kind: str
    owner: str | None
    payload: dict[str, Any]
    stream: str
    matching: dict[str, Any] | None = None
    review_records: tuple[dict[str, Any], ...] = ()
    head_occurred_at: datetime | None = None

    def __post_init__(self):
        if self.kind not in {
            "COHORT",
            "DEMAND",
            "RECOMMENDATION",
            "PUBLIC_GITHUB",
            "TREND",
        }:
            raise ValueError("unsupported snapshot kind")
        if (self.kind == "RECOMMENDATION") != bool(self.owner):
            raise ValueError("only recommendation snapshots have a user owner")
        if not self.stream or len(self.stream) > 160:
            raise ValueError("invalid snapshot stream")
        if self.matching is not None and self.kind != "RECOMMENDATION":
            raise ValueError("only recommendation snapshots have matching rows")
        if self.review_records and self.kind != "COHORT":
            raise ValueError("only cohort snapshots have Registry review records")
        if self.head_occurred_at is not None and self.head_occurred_at.tzinfo is None:
            raise ValueError("head timestamp needs a timezone")

    @property
    def snapshot_id(self) -> str:
        return "c-" + digest(
            {"kind": self.kind, "owner": self.owner, "payload": self.payload}
        )


@dataclass(frozen=True)
class Ticket:
    event_id: str
    kind: str
    owner: str | None
    occurred_at: datetime
    status: str
    token: str | None
    attempt: int
    results: list[dict[str, str]]


class ComputeStore:
    def __init__(self, dsn: str, *, lease_seconds: int = 120):
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be between 1 and 3600")
        self._dsn = dsn
        self.lease_seconds = lease_seconds

    def _connect(self):
        return psycopg.connect(
            self._dsn,
            connect_timeout=5,
            row_factory=dict_row,
            options="-c statement_timeout=15000 -c lock_timeout=5000",
        )

    def ready(self) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT count(*) AS count FROM c_compute.schema_version "
                "WHERE version = ANY(%s)",
                (list(range(1, MIGRATION_VERSION + 1)),),
            ).fetchone()
            return row["count"] == MIGRATION_VERSION

    def bind_job_inputs(self, inputs: dict[str, tuple[str, str]]) -> None:
        """Pin verified completion paths before publishing, independently of compute versions.

        These completed validation events have no result snapshots. Reusing the
        existing event ledger keeps the first byte binding durable across restarts.
        """
        if not inputs:
            return
        expected = {
            "job-input-" + digest(path): digest(
                {"path": path, "batch_sha256": hashes[0], "manifest_sha256": hashes[1]}
            )
            for path, hashes in inputs.items()
        }
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO c_compute.event
                       (event_id, kind, owner, request_hash, occurred_at, state,
                        lease_token, lease_until, attempt)
                       VALUES (%s, 'JOB_INPUT', '', %s, clock_timestamp(), 'COMPLETED',
                               %s, clock_timestamp(), 1)
                       ON CONFLICT (event_id) DO NOTHING""",
                    [(key, expected[key], uuid4()) for key in sorted(expected)],
                )
            rows = conn.execute(
                "SELECT event_id, kind, owner, request_hash FROM c_compute.event "
                "WHERE event_id = ANY(%s)",
                (list(expected),),
            ).fetchall()
            if len(rows) != len(expected) or any(
                row["kind"] != "JOB_INPUT"
                or row["owner"] != ""
                or row["request_hash"] != expected[row["event_id"]]
                for row in rows
            ):
                raise IdempotencyConflict("verified completion input was replaced")

    def claim(
        self,
        *,
        event_id: str,
        kind: str,
        owner: str | None,
        occurred_at: datetime,
        request: dict[str, Any],
    ) -> Ticket:
        if (
            not event_id
            or len(event_id) > 128
            or kind not in {"JOB_BATCH", "ANALYSIS", "PUBLIC_REPO", "TREND"}
        ):
            raise ValueError("invalid event identity")
        if occurred_at.tzinfo is None:
            raise ValueError("event timestamp needs a timezone")
        if (kind == "ANALYSIS") != bool(owner) or (owner and len(owner) > 128):
            raise ValueError("invalid event owner")
        request_hash = digest(
            {
                "kind": kind,
                "owner": owner,
                "request": request,
                "occurred_at": occurred_at.astimezone(UTC).isoformat(),
            }
        )
        token = uuid4()
        with self._connect() as conn:
            inserted = conn.execute(
                """INSERT INTO c_compute.event
                   (event_id, kind, owner, request_hash, occurred_at, state,
                    lease_token, lease_until, attempt)
                   VALUES (%s, %s, %s, %s, %s, 'RUNNING', %s,
                           clock_timestamp() + %s * interval '1 second', 1)
                   ON CONFLICT (event_id) DO NOTHING RETURNING event_id""",
                (
                    event_id,
                    kind,
                    owner or "",
                    request_hash,
                    occurred_at,
                    token,
                    self.lease_seconds,
                ),
            ).fetchone()
            row = conn.execute(
                "SELECT *, lease_until > clock_timestamp() AS lease_alive "
                "FROM c_compute.event WHERE event_id = %s FOR UPDATE",
                (event_id,),
            ).fetchone()
            if row["owner"] != (owner or "") or row["kind"] != kind:
                raise IdempotencyConflict("event ID already has a different scope")
            settled = row["state"] == "COMPLETED" or (
                row["state"] == "RUNNING" and row["lease_alive"]
            )
            # A request_hash mismatch only misleads a caller that is about to be
            # handed an outcome it did not ask for: a COMPLETED ticket returns
            # its `results` as the answer to *this* request, and a live RUNNING
            # attempt is already producing them. Those stay conflicts.
            #
            # An unsettled ticket — FAILED, or RUNNING whose lease has expired —
            # has published nothing, so re-running it under the new content is
            # the correct outcome rather than an error. Refusing it instead
            # strands the event permanently: the row can never be reclaimed and
            # the only way out is deleting it by hand (S15P21E102-283).
            if settled and row["request_hash"] != request_hash:
                raise IdempotencyConflict(
                    "event ID already has different content or scope"
                )
            if inserted:
                ticket_token = str(token)
            elif settled:
                ticket_token = None
            else:
                row = conn.execute(
                    """UPDATE c_compute.event SET state = 'RUNNING', lease_token = %s,
                       lease_until = clock_timestamp() + %s * interval '1 second',
                       attempt = attempt + 1, error_code = NULL, request_hash = %s,
                       updated_at = clock_timestamp()
                       WHERE event_id = %s RETURNING *""",
                    (token, self.lease_seconds, request_hash, event_id),
                ).fetchone()
                ticket_token = str(token)
            return Ticket(
                event_id,
                kind,
                owner,
                occurred_at,
                row["state"],
                ticket_token,
                row["attempt"],
                row["results"],
            )

    def renew(self, ticket: Ticket) -> bool:
        """Extend only this still-live RUNNING attempt; never resurrect a lease."""
        if ticket.token is None:
            return False
        with self._connect() as conn:
            row = conn.execute(
                """UPDATE c_compute.event
                   SET lease_until = clock_timestamp() + %s * interval '1 second',
                       updated_at = clock_timestamp()
                   WHERE event_id = %s AND kind = %s AND owner = %s
                     AND lease_token = %s AND state = 'RUNNING'
                     AND lease_until > clock_timestamp()
                   RETURNING event_id""",
                (
                    self.lease_seconds,
                    ticket.event_id,
                    ticket.kind,
                    ticket.owner or "",
                    ticket.token,
                ),
            ).fetchone()
            return row is not None

    def complete(
        self,
        ticket: Ticket,
        artifacts: list[Artifact],
        *,
        head_merger: Callable[
            [Mapping[str, Any], Mapping[str, Any] | None], dict[str, Any]
        ]
        | None = None,
    ) -> list[dict[str, str]]:
        allowed = {
            "JOB_BATCH": {"COHORT", "DEMAND"},
            "ANALYSIS": {"RECOMMENDATION"},
            "PUBLIC_REPO": {"PUBLIC_GITHUB"},
            "TREND": {"TREND"},
        }[ticket.kind]
        if not artifacts or any(
            a.kind not in allowed or a.owner != ticket.owner for a in artifacts
        ):
            raise ValueError("result scope does not match event")
        if len({(a.kind, a.stream) for a in artifacts}) != len(artifacts):
            raise ValueError("duplicate result stream")
        if head_merger is not None and ticket.kind != "TREND":
            raise ValueError("head merging is only supported for Trend events")
        with self._connect() as conn:
            row = conn.execute(
                """SELECT event_id FROM c_compute.event
                   WHERE event_id = %s AND lease_token = %s AND kind = %s AND owner = %s AND state = 'RUNNING'
                     AND lease_until > clock_timestamp() FOR UPDATE""",
                (ticket.event_id, ticket.token, ticket.kind, ticket.owner or ""),
            ).fetchone()
            if not row:
                raise LeaseLost("attempt no longer owns a live lease")
            if head_merger is not None:
                # A can publish several weeks with the same ingestion timestamp,
                # and separate partitions/workers can complete them concurrently.
                # Lock every stream in stable order before reading its current
                # payload so accumulation and head replacement are one operation.
                for artifact in sorted(
                    artifacts,
                    key=lambda value: (value.kind, value.owner or "", value.stream),
                ):
                    lock_scope = digest(
                        {
                            "kind": artifact.kind,
                            "owner": artifact.owner,
                            "stream": artifact.stream,
                        }
                    )
                    conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (lock_scope,),
                    )
                merged_artifacts = []
                for artifact in artifacts:
                    previous = conn.execute(
                        """SELECT s.payload
                           FROM c_compute.head h JOIN c_compute.snapshot s
                             ON s.snapshot_id = h.snapshot_id
                           WHERE h.kind = %s AND h.owner = %s AND h.stream = %s
                           FOR UPDATE OF h""",
                        (artifact.kind, artifact.owner or "", artifact.stream),
                    ).fetchone()
                    merged_artifacts.append(
                        replace(
                            artifact,
                            payload=head_merger(
                                artifact.payload,
                                None if previous is None else previous["payload"],
                            ),
                        )
                    )
                artifacts = merged_artifacts
            identified = [(artifact, artifact.snapshot_id) for artifact in artifacts]
            results = [
                {"kind": artifact.kind, "snapshot_id": snapshot_id}
                for artifact, snapshot_id in identified
            ]
            for artifact, snapshot_id in identified:
                conn.execute(
                    """INSERT INTO c_compute.snapshot(snapshot_id, kind, owner, payload)
                       VALUES (%s, %s, %s, %s) ON CONFLICT(snapshot_id) DO NOTHING""",
                    (
                        snapshot_id,
                        artifact.kind,
                        artifact.owner or "",
                        Jsonb(artifact.payload),
                    ),
                )
                if artifact.matching is not None:
                    self._store_matching(conn, artifact, snapshot_id)
                if artifact.review_records:
                    from worker.reviews import insert_reviews

                    insert_reviews(conn, artifact.review_records, snapshot_id)
                head_sql = (
                    """INSERT INTO c_compute.head(kind, owner, stream, snapshot_id, occurred_at, event_id)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT(kind, owner, stream) DO UPDATE
                       SET snapshot_id = EXCLUDED.snapshot_id,
                           occurred_at = GREATEST(c_compute.head.occurred_at, EXCLUDED.occurred_at),
                           event_id = EXCLUDED.event_id"""
                    if head_merger is not None
                    else """INSERT INTO c_compute.head(kind, owner, stream, snapshot_id, occurred_at, event_id)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT(kind, owner, stream) DO UPDATE
                       SET snapshot_id = EXCLUDED.snapshot_id, occurred_at = EXCLUDED.occurred_at,
                           event_id = EXCLUDED.event_id
                       WHERE (EXCLUDED.occurred_at, EXCLUDED.event_id) >
                             (c_compute.head.occurred_at, c_compute.head.event_id)"""
                )
                conn.execute(
                    head_sql,
                    (
                        artifact.kind,
                        artifact.owner or "",
                        artifact.stream,
                        snapshot_id,
                        artifact.head_occurred_at or ticket.occurred_at,
                        ticket.event_id,
                    ),
                )
            conn.execute(
                """UPDATE c_compute.event SET state = 'COMPLETED', results = %s,
                   error_code = NULL, updated_at = clock_timestamp() WHERE event_id = %s""",
                (Jsonb(results), ticket.event_id),
            )
        return results

    @staticmethod
    def _store_matching(conn, artifact: Artifact, snapshot_id: str) -> None:
        matching = artifact.matching
        reference = artifact.payload.get("job_matching_ref")
        if not isinstance(matching, dict) or not isinstance(reference, dict):
            raise TypeError("matching storage requires an immutable reference")
        cohort_snapshot_id = reference.get("cohort_snapshot_id")
        metadata = matching.get("metadata")
        sources = matching.get("sources")
        assessments = matching.get("assessments")
        if (
            not isinstance(cohort_snapshot_id, str)
            or not isinstance(metadata, dict)
            or not isinstance(sources, list)
            or not isinstance(assessments, list)
            or reference.get("schema_version") != "job-matching-storage/v2"
            or reference.get("calculation_snapshot_id")
            != matching.get("calculation_snapshot_id")
            or reference.get("job_count") != matching.get("total_count")
            or metadata.get("user_id") != artifact.owner
            or metadata.get("analysis_id") != artifact.payload.get("analysis_id")
            or metadata.get("cohort_id") != artifact.payload.get("cohort_id")
        ):
            raise ValueError("matching storage scope mismatch")

        source_by_id = {source.get("job_id"): source for source in sources}
        if len(source_by_id) != len(sources) or set(source_by_id) != {
            assessment.get("job_id") for assessment in assessments
        }:
            raise ValueError("matching source references are incomplete")
        source_hashes = {
            job_id: digest(source) for job_id, source in source_by_id.items()
        }
        source_rows = [
            (
                cohort_snapshot_id,
                job_id,
                Jsonb(source),
                source_hashes[job_id],
            )
            for job_id, source in source_by_id.items()
        ]
        if source_rows:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO c_compute.matching_source
                       (cohort_snapshot_id, job_id, payload, source_hash)
                       VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    source_rows,
                )
            persisted = conn.execute(
                "SELECT job_id, source_hash FROM c_compute.matching_source "
                "WHERE cohort_snapshot_id = %s AND job_id = ANY(%s)",
                (cohort_snapshot_id, list(source_by_id)),
            ).fetchall()
            if len(persisted) != len(source_hashes) or any(
                row["source_hash"] != source_hashes.get(row["job_id"])
                for row in persisted
            ):
                raise StoredMatchingIntegrityError(
                    "immutable matching source changed for a cohort"
                )

        metadata_hash = digest(metadata)
        conn.execute(
            """INSERT INTO c_compute.matching_calculation
               (recommendation_snapshot_id, storage_version,
                calculation_snapshot_id, owner,
                cohort_snapshot_id, analysis_id, cohort_id, metadata, metadata_hash,
                total_count, eligible_count, conditional_count, stored_bytes)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT DO NOTHING""",
            (
                snapshot_id,
                reference["schema_version"],
                matching["calculation_snapshot_id"],
                artifact.owner,
                cohort_snapshot_id,
                metadata["analysis_id"],
                metadata["cohort_id"],
                Jsonb(metadata),
                metadata_hash,
                matching["total_count"],
                matching["eligible_count"],
                matching["conditional_count"],
                matching["stored_bytes"],
            ),
        )
        calculation = conn.execute(
            "SELECT * FROM c_compute.matching_calculation "
            "WHERE recommendation_snapshot_id = %s",
            (snapshot_id,),
        ).fetchone()
        expected_calculation = (
            reference["schema_version"],
            matching["calculation_snapshot_id"],
            artifact.owner,
            cohort_snapshot_id,
            metadata["analysis_id"],
            metadata["cohort_id"],
            metadata_hash,
            matching["total_count"],
            matching["eligible_count"],
            matching["conditional_count"],
            matching["stored_bytes"],
        )
        actual_calculation = (
            calculation["storage_version"],
            calculation["calculation_snapshot_id"],
            calculation["owner"],
            calculation["cohort_snapshot_id"],
            calculation["analysis_id"],
            calculation["cohort_id"],
            calculation["metadata_hash"],
            calculation["total_count"],
            calculation["eligible_count"],
            calculation["conditional_count"],
            calculation["stored_bytes"],
        )
        if actual_calculation != expected_calculation:
            raise StoredMatchingIntegrityError("matching calculation was replaced")

        assessment_hashes = {
            row["job_id"]: digest(row["assessment"]) for row in assessments
        }
        assessment_rows = [
            (
                snapshot_id,
                cohort_snapshot_id,
                row["position"],
                row["job_id"],
                row["eligibility"],
                Jsonb(row["assessment"]),
                assessment_hashes[row["job_id"]],
            )
            for row in assessments
        ]
        if assessment_rows:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO c_compute.matching_job
                       (recommendation_snapshot_id, cohort_snapshot_id, position,
                        job_id, eligibility, assessment, assessment_hash)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT DO NOTHING""",
                    assessment_rows,
                )
        persisted = conn.execute(
            """SELECT job_id, position, eligibility, assessment_hash
               FROM c_compute.matching_job
               WHERE recommendation_snapshot_id = %s""",
            (snapshot_id,),
        ).fetchall()
        expected_rows = {
            row["job_id"]: (
                row["position"],
                row["eligibility"],
                assessment_hashes[row["job_id"]],
            )
            for row in assessments
        }
        if len(persisted) != len(expected_rows) or any(
            (row["position"], row["eligibility"], row["assessment_hash"])
            != expected_rows.get(row["job_id"])
            for row in persisted
        ):
            raise StoredMatchingIntegrityError("matching assessment rows changed")

    def fail(self, ticket: Ticket, code: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE c_compute.event SET state = 'FAILED', error_code = %s,
                   updated_at = clock_timestamp()
                   WHERE event_id = %s AND lease_token = %s AND state = 'RUNNING'""",
                (code, ticket.event_id, ticket.token),
            )

    def get_snapshot(self, snapshot_id: str, *, owner: str | None) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT snapshot_id, kind, payload FROM c_compute.snapshot "
                "WHERE snapshot_id = %s AND owner = %s",
                (snapshot_id, owner or ""),
            ).fetchone()
            return dict(row) if row else None

    def query_reviews(self, *, status=None, after=None, limit: int = 50):
        from worker.reviews import query_reviews

        with self._connect() as conn:
            return query_reviews(conn, status=status, after=after, limit=limit)

    def get_review(self, review_id: str):
        from worker.reviews import get_review

        with self._connect() as conn:
            return get_review(conn, review_id)

    def resolve_review(
        self,
        *,
        review_id: str,
        mapper,
        actor: str,
        note: str,
        idempotency_key: str,
        expected_version: int,
        tech_id: str,
    ):
        from worker.reviews import resolve_review

        with self._connect() as conn:
            return resolve_review(
                conn,
                review_id=review_id,
                mapper=mapper,
                actor=actor,
                note=note,
                idempotency_key=idempotency_key,
                expected_version=expected_version,
                tech_id=tech_id,
            )

    def reprocess_review(
        self,
        *,
        review_id: str,
        mapper,
        actor: str,
        note: str,
        idempotency_key: str,
        expected_version: int,
    ):
        from worker.reviews import reprocess_review

        with self._connect() as conn:
            return reprocess_review(
                conn,
                review_id=review_id,
                mapper=mapper,
                actor=actor,
                note=note,
                idempotency_key=idempotency_key,
                expected_version=expected_version,
            )

    @staticmethod
    def _matching_header(conn, snapshot_id: str, owner: str) -> dict | None:
        row = conn.execute(
            """SELECT s.snapshot_id,
                      c.storage_version, c.calculation_snapshot_id, c.owner,
                      c.cohort_snapshot_id,
                      c.analysis_id, c.cohort_id,
                      c.metadata, c.metadata_hash, c.total_count, c.eligible_count,
                      c.conditional_count, c.stored_bytes
               FROM c_compute.snapshot s
               LEFT JOIN c_compute.matching_calculation c
                 ON c.recommendation_snapshot_id = s.snapshot_id
               WHERE s.snapshot_id = %s AND s.owner = %s
                 AND s.kind = 'RECOMMENDATION'""",
            (snapshot_id, owner),
        ).fetchone()
        if row is None:
            return None
        if row["calculation_snapshot_id"] is None:
            legacy = conn.execute(
                "SELECT payload ? 'job_matching' AS has_embedded, "
                "payload ? 'job_matching_ref' AS has_reference "
                "FROM c_compute.snapshot WHERE snapshot_id = %s",
                (snapshot_id,),
            ).fetchone()
            if legacy["has_reference"]:
                raise StoredMatchingIntegrityError("matching reference has no rows")
            return {
                "status": "LEGACY_EMBEDDED"
                if legacy["has_embedded"]
                else "NOT_PREPARED"
            }
        metadata = row["metadata"]
        if (
            not isinstance(metadata, dict)
            or row["storage_version"] != "job-matching-storage/v2"
            or row["owner"] != owner
            or metadata.get("user_id") != owner
            or metadata.get("analysis_id") != row["analysis_id"]
            or metadata.get("cohort_id") != row["cohort_id"]
            or digest(metadata) != row["metadata_hash"]
            or row["total_count"] != row["eligible_count"] + row["conditional_count"]
        ):
            raise StoredMatchingIntegrityError("stored matching scope mismatch")
        return {"status": "READY", **dict(row)}

    @staticmethod
    def _restore_matching_rows(rows: list[dict]) -> list[dict[str, Any]]:
        from job.matching import restore_job_assessment

        restored = []
        for row in rows:
            try:
                if (
                    row["source"] is None
                    or digest(row["source"]) != row["source_hash"]
                    or digest(row["assessment"]) != row["assessment_hash"]
                    or row["source"].get("job_id") != row["job_id"]
                ):
                    raise ValueError("matching row hash or reference mismatch")
                item = restore_job_assessment(row["source"], row["assessment"])
                if item.job.eligibility != row["eligibility"]:
                    raise ValueError("matching eligibility reference mismatch")
                restored.append(item.model_dump(mode="json"))
            except (KeyError, TypeError, ValueError) as exc:
                raise StoredMatchingIntegrityError(
                    "stored matching row is inconsistent"
                ) from exc
        return restored

    def get_matching_page(
        self,
        snapshot_id: str,
        *,
        owner: str,
        offset: int,
        limit: int,
        include_conditional: bool,
    ) -> dict | None:
        with self._connect() as conn:
            header = self._matching_header(conn, snapshot_id, owner)
            if header is None or header["status"] != "READY":
                return header
            selected_count = (
                header["total_count"]
                if include_conditional
                else header["eligible_count"]
            )
            if offset >= selected_count:
                return {**header, "items": [], "has_next": False}
            eligibility_sql = (
                "" if include_conditional else "AND eligibility = 'ELIGIBLE'"
            )
            rows = conn.execute(
                f"""SELECT j.job_id, j.eligibility, j.assessment,
                           j.assessment_hash, source.payload AS source,
                           source.source_hash
                    FROM (
                        SELECT job_id, eligibility, assessment, assessment_hash,
                               cohort_snapshot_id, position
                        FROM c_compute.matching_job
                        WHERE recommendation_snapshot_id = %s {eligibility_sql}
                        ORDER BY position LIMIT %s OFFSET %s
                    ) j
                    LEFT JOIN c_compute.matching_source source
                      ON source.cohort_snapshot_id = j.cohort_snapshot_id
                     AND source.job_id = j.job_id
                    ORDER BY j.position""",
                (snapshot_id, limit + 1, offset),
            ).fetchall()
            has_next = len(rows) > limit
            return {
                **header,
                "items": self._restore_matching_rows(rows[:limit]),
                "has_next": has_next,
            }

    def get_matching_detail(
        self, snapshot_id: str, *, owner: str, job_id: str
    ) -> dict | None:
        with self._connect() as conn:
            header = self._matching_header(conn, snapshot_id, owner)
            if header is None or header["status"] != "READY":
                return header
            row = conn.execute(
                """SELECT j.job_id, j.eligibility, j.assessment,
                          j.assessment_hash, source.payload AS source,
                          source.source_hash
                   FROM c_compute.matching_job j
                   LEFT JOIN c_compute.matching_source source
                     ON source.cohort_snapshot_id = j.cohort_snapshot_id
                    AND source.job_id = j.job_id
                   WHERE j.recommendation_snapshot_id = %s AND j.job_id = %s""",
                (snapshot_id, job_id),
            ).fetchone()
            return {
                **header,
                "item": self._restore_matching_rows([row])[0] if row else None,
            }

    def get_head(self, kind: str, owner: str | None, stream: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT snapshot_id FROM c_compute.head WHERE kind = %s AND owner = %s AND stream = %s",
                (kind, owner or "", stream),
            ).fetchone()
            return row["snapshot_id"] if row else None

    def get_job_head_pair(self, stream: str) -> dict[str, str] | None:
        """Read one coherent COHORT/DEMAND completion without split head reads."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT kind, snapshot_id, event_id FROM c_compute.head
                   WHERE owner = '' AND stream = %s AND kind = ANY(%s)""",
                (stream, ["COHORT", "DEMAND"]),
            ).fetchall()
        by_kind = {row["kind"]: row for row in rows}
        if set(by_kind) != {"COHORT", "DEMAND"}:
            return None
        if by_kind["COHORT"]["event_id"] != by_kind["DEMAND"]["event_id"]:
            return None
        return {
            "event_id": by_kind["COHORT"]["event_id"],
            "cohort_snapshot_id": by_kind["COHORT"]["snapshot_id"],
            "demand_snapshot_id": by_kind["DEMAND"]["snapshot_id"],
        }

    def get_head_snapshot(
        self, kind: str, owner: str | None, stream: str
    ) -> dict[str, Any] | None:
        """Resolve a head and its immutable payload in one read transaction."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT h.snapshot_id, h.event_id, h.occurred_at, s.payload
                   FROM c_compute.head h JOIN c_compute.snapshot s
                     ON s.snapshot_id = h.snapshot_id
                   WHERE h.kind = %s AND h.owner = %s AND h.stream = %s""",
                (kind, owner or "", stream),
            ).fetchone()
        return dict(row) if row else None

    def get_head_snapshots(
        self, *, kind: str, owner: str | None, streams: tuple[str, ...]
    ) -> dict[str, dict[str, Any]]:
        """Resolve bounded immutable heads and payloads in one read transaction."""
        if not streams:
            return {}
        if len(streams) > 10 or len(streams) != len(set(streams)):
            raise ValueError("invalid head stream selection")
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT h.stream, h.snapshot_id, h.event_id, h.occurred_at, s.payload
                   FROM c_compute.head h JOIN c_compute.snapshot s
                     ON s.snapshot_id = h.snapshot_id
                   WHERE h.kind = %s AND h.owner = %s AND h.stream = ANY(%s)""",
                (kind, owner or "", list(streams)),
            ).fetchall()
        return {row["stream"]: dict(row) for row in rows}

    def get_head_payloads(
        self, *, kind: str, owner: str | None, streams: tuple[str, ...]
    ) -> dict[str, dict]:
        """Load a bounded set of immutable head payloads in one transaction."""
        if not streams:
            return {}
        if len(streams) > 256 or len(streams) != len(set(streams)):
            raise ValueError("invalid head stream selection")
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT h.stream, s.payload
                   FROM c_compute.head h JOIN c_compute.snapshot s
                     ON s.snapshot_id = h.snapshot_id
                   WHERE h.kind = %s AND h.owner = %s AND h.stream = ANY(%s)""",
                (kind, owner or "", list(streams)),
            ).fetchall()
        return {row["stream"]: row["payload"] for row in rows}

    def select_public_snapshot(
        self, *, registry_version: str, include_partial: bool, week_start: str
    ) -> tuple[str, dict] | None:
        """Newest PUBLIC_GITHUB head compatible with one weekly observation."""
        try:
            requested_week = date.fromisoformat(week_start)
        except (TypeError, ValueError):
            raise ValueError("week_start must be an ISO date") from None
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT h.snapshot_id, s.payload
                   FROM c_compute.head h JOIN c_compute.snapshot s
                     ON s.snapshot_id = h.snapshot_id
                   WHERE h.kind = 'PUBLIC_GITHUB' AND h.owner = ''
                   ORDER BY h.occurred_at DESC, h.event_id DESC"""
            ).fetchall()
        for row in rows:
            payload = row["payload"]
            result = (
                payload.get("result", payload) if isinstance(payload, dict) else None
            )
            if (
                isinstance(result, dict)
                and result.get("registry_version") == registry_version
                and result.get("include_partial") is include_partial
                and _public_payload_covers_week(result, requested_week)
            ):
                return row["snapshot_id"], payload
        return None


def _public_payload_covers_week(result: dict, requested_week) -> bool:
    records = result.get("records")
    if not isinstance(records, list | tuple):
        return False
    included = [
        record
        for record in records
        if isinstance(record, dict) and record.get("included_in_denominator") is True
    ]
    if not included:
        return False
    week_end = requested_week + timedelta(days=6)
    expected_period = f"{requested_week.isoformat()}/{week_end.isoformat()}"
    for record in included:
        # Exact, not overlapping or containing. A MONTH PUBLIC overlaps the week
        # that starts on its last day by one day out of seven, and contains an
        # interior week entirely, and both used to select. Either way the
        # denominator was built over a different period than the activity rows
        # the week carries, which is what surfaced downstream as
        # PUBLIC_REPOSITORY_MISSING_ACTIVITY. A WEEK observation takes the PUBLIC
        # published for that week or none at all.
        if record.get("target_period") != expected_period:
            return False
        try:
            start = datetime.fromisoformat(str(record["activity_period_start"])).date()
            end = datetime.fromisoformat(str(record["activity_period_end"])).date()
        except (KeyError, ValueError):
            return False
        if start != requested_week or end != week_end:
            return False
    return True


def _target_period_covers_week(value: object, requested_week: date) -> bool:
    """Accept the current A date range and the legacy monthly shorthand."""
    if not isinstance(value, str):
        return False
    week_end = requested_week + timedelta(days=6)
    if len(value) == 7:
        return value in {
            requested_week.strftime("%Y-%m"),
            week_end.strftime("%Y-%m"),
        }
    parts = value.split("/")
    if len(parts) != 2:
        return False
    try:
        start, end = (date.fromisoformat(part) for part in parts)
    except ValueError:
        return False
    return _period_overlaps_week(start, end, requested_week)


def _period_overlaps_week(start: date, end: date, requested_week: date) -> bool:
    week_end = requested_week + timedelta(days=6)
    return start <= week_end and requested_week <= end
