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

# 출처마다 값이 들어 있는 point 필드가 다르다. 지표 이름이 곧 단위라, 한 필드를
# 모든 출처에 맞추면 EVENTS 와 POSTINGS 가 한 축에 섞인다.
TREND_VALUE_KEYS: dict[str, str] = {
    # GH Archive 의 기술별 지표는 `active_repo_count` 다 — 그 기간에 그 기술이 관측된
    # 저장소 수. 같은 point 의 `event_count` 는 순위에 쓸 수 없다: 그것은 기술의
    # 이벤트가 아니라 **그 기술을 쓰는 저장소들의 전체 GH Archive 활동 합**이라,
    # 한 저장소가 여러 기술을 쓰면 그 저장소의 활동량이 기술마다 통째로 다시 더해진다.
    # Production 실측 — 2026-08-31 주간은 기술별 합 1,191,450 vs 코호트 실제 303,939
    # (약 3.9배), 2026-08 월별도 약 2.2배. 분모도 없어 비율로 환산할 수 없다.
    "GITHUB_GH_ARCHIVE": "active_repo_count",
    "JOB": "value",
}

TREND_DENOMINATOR_KEYS: dict[str, str] = {
    # 순위 값을 비율로 읽으려면 모집단이 필요하다. 주차마다 코호트 크기가 달라
    # (2026-08-31 = 4,045 / 2026-09-07 = 133) raw count 를 기간끼리 비교하면 틀린다.
    "GITHUB_GH_ARCHIVE": "sample_repo_count",
    "JOB": "denominator",
}

TREND_RANKING_UNITS: dict[str, str] = {
    # 순위에 쓰는 **필드의** 단위다. snapshot 이 선언한 headline `unit`(EVENTS)과 다른
    # 것이 정상이다 — 그쪽은 `event_count` 의 단위이고, 순위는 그 값을 쓰지 않는다.
    "GITHUB_GH_ARCHIVE": "REPOSITORIES",
    "JOB": "POSTINGS",
}

MIGRATION_VERSION = 8
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
    Path(__file__).resolve().parents[2]
    / "BE/src/main/resources/db/c-compute/005_job_search_projection.sql",
    Path(__file__).resolve().parents[2]
    / "BE/src/main/resources/db/c-compute/006_current_result.sql",
    Path(__file__).resolve().parents[2]
    / "BE/src/main/resources/db/c-compute/007_projection_publication_safety.sql",
    Path(__file__).resolve().parents[2]
    / "BE/src/main/resources/db/c-compute/008_job_projection_market_sidecar.sql",
)


class IdempotencyConflict(ValueError):
    """The caller reused an event ID for a different immutable request."""


class LeaseLost(RuntimeError):
    """Another attempt owns the event, or this attempt's lease expired."""


class StoredMatchingIntegrityError(RuntimeError):
    """Persisted matching references disagree without exposing stored content."""


CURRENT_RESULT_CONTRACT_VERSION = "current-user-result/v1"


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
        conn.execute("SET LOCAL lock_timeout = '5s'")
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
    projection_version_id: str | None = None
    result_target_key: str | None = None

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
        if self.projection_version_id is not None and (
            self.kind != "RECOMMENDATION"
            or len(self.projection_version_id) > 80
            or not self.projection_version_id.startswith("jp-")
        ):
            raise ValueError("only recommendation results can pin a projection")
        if self.result_target_key is not None and (
            self.kind != "RECOMMENDATION"
            or not self.result_target_key
            or len(self.result_target_key) > 200
            or any(ord(character) < 32 for character in self.result_target_key)
        ):
            raise ValueError("invalid recommendation result target key")

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

    def publish_job_projection(self, projection) -> str:
        from worker.job_projection_store import JobProjectionStore

        return JobProjectionStore(self._dsn).publish(projection)

    def get_job_projection_head(self) -> dict[str, Any] | None:
        from worker.job_projection_store import JobProjectionStore

        return JobProjectionStore(self._dsn).head()

    def query_job_projection_demand(self, criteria, *, projection_version_id=None):
        from worker.job_projection_store import JobProjectionStore

        return JobProjectionStore(self._dsn).demand(
            criteria, projection_version_id=projection_version_id
        )

    def query_job_projection_demand_summary(
        self, criteria, *, projection_version_id=None
    ):
        from worker.job_projection_store import JobProjectionStore

        return JobProjectionStore(self._dsn).summary(
            criteria, projection_version_id=projection_version_id
        )

    def query_job_projection_cohort(self, criteria, *, projection_version_id):
        """Restore the pinned personalized cohort; never used by Preview."""

        from worker.job_projection_store import JobProjectionStore

        return JobProjectionStore(self._dsn).cohort(
            criteria, projection_version_id=projection_version_id
        )

    def query_job_projection_selected_keys(self, criteria, *, projection_version_id):
        """Read only selector identities for bounded SQL/Python shadow parity."""

        from worker.job_projection_store import JobProjectionStore

        return JobProjectionStore(self._dsn).selected_job_keys(
            criteria, projection_version_id=projection_version_id
        )

    def store_projection_compatibility_pair(self, cohort, demand):
        """Idempotently persist one immutable projection COHORT/DEMAND pair."""

        if (
            cohort.projection_version_id is None
            or cohort.projection_version_id != demand.projection_version_id
        ):
            raise ValueError("projection compatibility pair identity disagrees")
        artifacts = (
            Artifact("COHORT", None, cohort.model_dump(mode="json"), "compatibility"),
            Artifact("DEMAND", None, demand.model_dump(mode="json"), "compatibility"),
        )
        with self._connect() as conn:
            for artifact in artifacts:
                conn.execute(
                    """INSERT INTO c_compute.snapshot(snapshot_id, kind, owner, payload)
                       VALUES (%s, %s, '', %s) ON CONFLICT(snapshot_id) DO NOTHING""",
                    (artifact.snapshot_id, artifact.kind, Jsonb(artifact.payload)),
                )
        return {
            "cohort_snapshot_id": artifacts[0].snapshot_id,
            "demand_snapshot_id": artifacts[1].snapshot_id,
        }

    def resolve_job_projection_selector(self, selector):
        head = self.get_job_projection_head()
        if head is None:
            return None
        criteria = selector.criteria_at(head["observed_at"])
        return criteria, self.query_job_projection_demand(
            criteria, projection_version_id=head["projection_version_id"]
        )

    def resolve_job_projection_summary(self, selector):
        head = self.get_job_projection_head()
        if head is None:
            return None
        criteria = selector.criteria_at(head["observed_at"])
        return criteria, self.query_job_projection_demand_summary(
            criteria, projection_version_id=head["projection_version_id"]
        )

    def get_job_projection_readiness(self) -> dict[str, Any]:
        from worker.job_projection_store import JobProjectionStore

        return JobProjectionStore(self._dsn).readiness()

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
            results = []
            for artifact, snapshot_id in identified:
                result_reference = {
                    "kind": artifact.kind,
                    "snapshot_id": snapshot_id,
                }
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
                    result_reference["result_id"] = self._store_matching(
                        conn,
                        artifact,
                        snapshot_id,
                        source_occurred_at=artifact.head_occurred_at or ticket.occurred_at,
                        source_order_key=ticket.event_id,
                    )
                results.append(result_reference)
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
    def _store_matching(
        conn,
        artifact: Artifact,
        snapshot_id: str,
        *,
        source_occurred_at: datetime,
        source_order_key: str,
    ) -> str:
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
        projection_version_id = artifact.projection_version_id
        if projection_version_id is not None:
            projection = conn.execute(
                """SELECT projection_version_id
                   FROM c_compute.job_projection_version
                   WHERE projection_version_id = %s AND state = 'PUBLISHED'""",
                (projection_version_id,),
            ).fetchone()
            if projection is None:
                raise ValueError("pinned projection is not published")
        fact_by_job_id: dict[str, str] = {}
        if projection_version_id is not None and source_by_id:
            facts = conn.execute(
                """SELECT job_key, job_fact_id
                   FROM c_compute.job_projection_job
                   WHERE projection_version_id = %s AND job_key = ANY(%s)""",
                (projection_version_id, list(source_by_id)),
            ).fetchall()
            fact_by_job_id = {row["job_key"]: row["job_fact_id"] for row in facts}
            if set(fact_by_job_id) != set(source_by_id):
                raise StoredMatchingIntegrityError(
                    "projection matching source is missing a pinned job fact"
                )

        evidence_version = str(
            artifact.payload.get("evidence_input_version")
            or metadata.get("evidence_input_version")
            or "legacy-unknown"
        )
        contract_version = ":".join(
            (
                CURRENT_RESULT_CONTRACT_VERSION,
                str(artifact.payload.get("schema_version", "unknown")),
                str(artifact.payload.get("algorithm_version", "unknown")),
            )
        )
        compact_payload = {
            key: value
            for key, value in artifact.payload.items()
            if key
            not in {
                "jobs",
                "matching_jobs",
                "job_matching",
                "job_matching_ref",
            }
        }
        compact_payload.update(
            {
                "recommendation_snapshot_id": snapshot_id,
                "calculation_snapshot_id": matching["calculation_snapshot_id"],
                "matching_total_count": matching["total_count"],
                "matching_eligible_count": matching["eligible_count"],
                "matching_conditional_count": matching["conditional_count"],
            }
        )
        compact_hash = digest(compact_payload)
        target_key = artifact.result_target_key or artifact.stream
        proposed_result_id = "ur-" + digest(
            {
                "user_id": artifact.owner,
                "target_key": target_key,
                "evidence_version": evidence_version,
                "projection_version_id": projection_version_id,
                "compute_contract_version": contract_version,
                "recommendation_snapshot_id": snapshot_id,
                "compact_payload_hash": compact_hash,
            }
        )
        canonical = conn.execute(
            """SELECT result_id, user_id, target_key, evidence_version,
                      projection_version_id, compute_contract_version, status,
                      recommendation_snapshot_id, compact_payload, payload_hash
               FROM c_compute.user_result
               WHERE recommendation_snapshot_id = %s""",
            (snapshot_id,),
        ).fetchone()
        if canonical is None:
            result_id = proposed_result_id
            conn.execute(
                """INSERT INTO c_compute.user_result
                   (result_id, user_id, target_key, evidence_version,
                    projection_version_id, compute_contract_version, status,
                    recommendation_snapshot_id, compact_payload, payload_hash)
                   VALUES (%s, %s, %s, %s, %s, %s, 'READY', %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    result_id,
                    artifact.owner,
                    target_key,
                    evidence_version,
                    projection_version_id,
                    contract_version,
                    snapshot_id,
                    Jsonb(compact_payload),
                    compact_hash,
                ),
            )
        else:
            if (
                not isinstance(canonical["compact_payload"], dict)
                or digest(canonical["compact_payload"]) != canonical["payload_hash"]
                or canonical["user_id"] != artifact.owner
                or canonical["evidence_version"] != evidence_version
                or canonical["projection_version_id"] != projection_version_id
                or canonical["compute_contract_version"] != contract_version
                or canonical["status"] != "READY"
            ):
                raise StoredMatchingIntegrityError("canonical user result is inconsistent")
            result_id = canonical["result_id"]
        expected_payload_hash = (
            canonical["payload_hash"] if canonical is not None else compact_hash
        )
        stored_result = conn.execute(
            """SELECT user_id, target_key, evidence_version, projection_version_id,
                      compute_contract_version, status, recommendation_snapshot_id,
                      payload_hash
               FROM c_compute.user_result WHERE result_id = %s""",
            (result_id,),
        ).fetchone()
        expected_result = (
            artifact.owner,
            stored_result["target_key"] if stored_result is not None else target_key,
            evidence_version,
            projection_version_id,
            contract_version,
            "READY",
            snapshot_id,
            expected_payload_hash,
        )
        if stored_result is None or tuple(stored_result.values()) != expected_result:
            raise StoredMatchingIntegrityError("current user result was replaced")
        source_rows = [
            (
                cohort_snapshot_id,
                job_id,
                fact_by_job_id.get(job_id),
                Jsonb(source),
                source_hashes[job_id],
            )
            for job_id, source in source_by_id.items()
        ]
        if source_rows:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO c_compute.matching_source
                       (cohort_snapshot_id, job_id, job_fact_id, payload, source_hash)
                       VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    source_rows,
                )
            persisted = conn.execute(
                "SELECT job_id, job_fact_id, source_hash "
                "FROM c_compute.matching_source "
                "WHERE cohort_snapshot_id = %s AND job_id = ANY(%s)",
                (cohort_snapshot_id, list(source_by_id)),
            ).fetchall()
            if projection_version_id is None and (
                len(persisted) != len(source_hashes)
                or any(
                    row["source_hash"] != source_hashes.get(row["job_id"])
                    for row in persisted
                )
            ):
                raise StoredMatchingIntegrityError(
                    "immutable matching source changed for a cohort"
                )
            if projection_version_id is not None:
                fact_rows = [
                    (
                        cohort_snapshot_id,
                        job_id,
                        fact_by_job_id[job_id],
                        Jsonb(source_by_id[job_id]),
                        source_hashes[job_id],
                    )
                    for job_id in source_by_id
                ]
                with conn.cursor() as cursor:
                    cursor.executemany(
                        """INSERT INTO c_compute.matching_source_fact
                           (cohort_snapshot_id, job_id, job_fact_id, payload, source_hash)
                           VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                        fact_rows,
                    )
                persisted_facts = conn.execute(
                    """SELECT job_id, job_fact_id, source_hash
                       FROM c_compute.matching_source_fact
                       WHERE cohort_snapshot_id = %s AND job_id = ANY(%s)
                         AND job_fact_id = ANY(%s)""",
                    (
                        cohort_snapshot_id,
                        list(source_by_id),
                        list(fact_by_job_id.values()),
                    ),
                ).fetchall()
                expected_facts = {
                    (job_id, fact_by_job_id[job_id]): source_hashes[job_id]
                    for job_id in source_by_id
                }
                if len(persisted_facts) != len(expected_facts) or any(
                    row["source_hash"]
                    != expected_facts.get((row["job_id"], row["job_fact_id"]))
                    for row in persisted_facts
                ):
                    raise StoredMatchingIntegrityError(
                        "immutable projection matching source changed"
                    )
                stored_fact_by_job_id = dict(fact_by_job_id)
            else:
                stored_fact_by_job_id = {
                    row["job_id"]: row["job_fact_id"] for row in persisted
                }
        else:
            stored_fact_by_job_id = {}

        metadata_hash = digest(metadata)
        conn.execute(
            """INSERT INTO c_compute.matching_calculation
               (recommendation_snapshot_id, storage_version,
                calculation_snapshot_id, owner,
                cohort_snapshot_id, analysis_id, cohort_id, metadata, metadata_hash,
                total_count, eligible_count, conditional_count, stored_bytes, result_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                result_id,
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
            result_id,
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
            calculation["result_id"],
        )
        if actual_calculation != expected_calculation:
            raise StoredMatchingIntegrityError("matching calculation was replaced")

        assessment_hashes = {
            row["job_id"]: digest(row["assessment"]) for row in assessments
        }
        assessment_rows = [
            (
                snapshot_id,
                result_id,
                cohort_snapshot_id,
                row["position"],
                row["job_id"],
                stored_fact_by_job_id.get(row["job_id"]),
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
                       (recommendation_snapshot_id, result_id, cohort_snapshot_id,
                        position, job_id, job_fact_id, eligibility, assessment,
                        assessment_hash)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        conn.execute(
            """INSERT INTO c_compute.user_result_head
               (user_id, target_key, result_id, previous_result_id,
                source_occurred_at, source_order_key)
               VALUES (%s, %s, %s, NULL, %s, %s)
               ON CONFLICT (user_id, target_key) DO UPDATE
               SET previous_result_id = CASE
                       WHEN c_compute.user_result_head.result_id <> EXCLUDED.result_id
                       THEN c_compute.user_result_head.result_id
                       ELSE c_compute.user_result_head.previous_result_id
                   END,
                   result_id = EXCLUDED.result_id,
                   source_occurred_at = EXCLUDED.source_occurred_at,
                   source_order_key = EXCLUDED.source_order_key,
                   updated_at = clock_timestamp()
               WHERE (EXCLUDED.source_occurred_at, EXCLUDED.source_order_key) >
                     (c_compute.user_result_head.source_occurred_at,
                      c_compute.user_result_head.source_order_key)""",
            (
                artifact.owner,
                target_key,
                result_id,
                source_occurred_at,
                source_order_key,
            ),
        )
        return result_id

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

    @staticmethod
    def _restore_user_result(
        row: Mapping[str, Any] | None, *, compare_projection: bool = False
    ) -> dict | None:
        if row is None:
            return None
        payload = row["compact_payload"]
        if not isinstance(payload, dict) or digest(payload) != row["payload_hash"]:
            raise StoredMatchingIntegrityError("current user result payload changed")
        current_projection_id = row.get("current_projection_version_id")
        stored_projection_id = row["projection_version_id"]
        stale = (
            compare_projection
            and current_projection_id is not None
            and stored_projection_id != current_projection_id
        )
        status = (
            "STALE"
            if stale
            else "LEGACY"
            if stored_projection_id is None
            else row["status"]
        )
        return {
            "result_id": row["result_id"],
            "user_id": row["user_id"],
            "target_key": row["target_key"],
            "evidence_version": row["evidence_version"],
            "projection_version_id": stored_projection_id,
            "current_projection_version_id": current_projection_id,
            "compute_contract_version": row["compute_contract_version"],
            "status": status,
            "recompute_required": stale,
            "recommendation_snapshot_id": row["recommendation_snapshot_id"],
            "payload": payload,
            "created_at": row["created_at"],
        }

    def get_user_result(
        self, result_id: str, *, owner: str, compare_projection: bool = False
    ) -> dict | None:
        """Read a new result by its ID or its legacy recommendation snapshot ID."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT r.*,
                          projection_head.projection_version_id
                              AS current_projection_version_id
                   FROM c_compute.user_result r
                   LEFT JOIN c_compute.job_projection_head projection_head
                     ON projection_head.stream = 'JOB_SEARCH'
                   WHERE r.user_id = %s
                     AND (r.result_id = %s OR r.recommendation_snapshot_id = %s)""",
                (owner, result_id, result_id),
            ).fetchone()
        return self._restore_user_result(row, compare_projection=compare_projection)

    def get_current_user_result(
        self, *, owner: str, target_key: str, compare_projection: bool = False
    ) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT r.*,
                          projection_head.projection_version_id
                              AS current_projection_version_id,
                          h.previous_result_id,
                          h.target_key AS head_target_key
                   FROM c_compute.user_result_head h
                   JOIN c_compute.user_result r ON r.result_id = h.result_id
                   LEFT JOIN c_compute.job_projection_head projection_head
                     ON projection_head.stream = 'JOB_SEARCH'
                   WHERE h.user_id = %s AND h.target_key = %s""",
                (owner, target_key),
            ).fetchone()
        result = self._restore_user_result(row, compare_projection=compare_projection)
        if result is not None:
            result["previous_result_id"] = row["previous_result_id"]
            result["target_key"] = row["head_target_key"]
        return result

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
    def _matching_header(
        conn, snapshot_id: str, owner: str, *, compare_projection: bool = False
    ) -> dict | None:
        row = conn.execute(
            """SELECT s.snapshot_id,
                      c.storage_version, c.calculation_snapshot_id, c.owner,
                      c.cohort_snapshot_id,
                      c.analysis_id, c.cohort_id,
                      c.metadata, c.metadata_hash, c.total_count, c.eligible_count,
                      c.conditional_count, c.stored_bytes, c.result_id,
                      result.projection_version_id,
                      result.compact_payload AS result_payload,
                      result.payload_hash AS result_payload_hash,
                      projection_head.projection_version_id
                          AS current_projection_version_id
               FROM c_compute.snapshot s
               LEFT JOIN c_compute.matching_calculation c
                 ON c.recommendation_snapshot_id = s.snapshot_id
               LEFT JOIN c_compute.user_result result ON result.result_id = c.result_id
               LEFT JOIN c_compute.job_projection_head projection_head
                 ON projection_head.stream = 'JOB_SEARCH'
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
        if row["result_id"] is not None and (
            not isinstance(row["result_payload"], dict)
            or digest(row["result_payload"]) != row["result_payload_hash"]
        ):
            raise StoredMatchingIntegrityError("stored user result payload changed")
        stale = (
            compare_projection
            and row["result_id"] is not None
            and row["current_projection_version_id"] is not None
            and row["projection_version_id"] != row["current_projection_version_id"]
        )
        result_status = (
            "STALE"
            if stale
            else "LEGACY"
            if row["projection_version_id"] is None
            else "READY"
        )
        return {"status": "READY", "result_status": result_status, **dict(row)}

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
                    or row.get("assessment_job_fact_id")
                    != row.get("source_job_fact_id")
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
        active_only: bool = False,
        as_of: datetime | None = None,
    ) -> dict | None:
        with self._connect() as conn:
            header = self._matching_header(
                conn, snapshot_id, owner, compare_projection=active_only
            )
            if header is None or header["status"] != "READY":
                return header
            active_join = ""
            active_params: tuple[Any, ...] = ()
            if active_only:
                projection = conn.execute(
                    "SELECT projection_version_id FROM c_compute.job_projection_head "
                    "WHERE stream = 'JOB_SEARCH'"
                ).fetchone()
                if projection is None:
                    raise LookupError("projection head unavailable")
                active_join = """JOIN c_compute.job_projection_job active
                    ON active.projection_version_id = %s
                   AND active.job_key = j.job_id
                   AND active.posting_status <> 'CLOSED'
                   AND (active.deadline IS NULL OR active.deadline > %s)
                   AND active.collected_at <= %s
                   AND (active.posted_at IS NULL OR active.posted_at <= %s)
                   AND active.body_status = 'TEXT_AVAILABLE'
                   AND NOT (active.quality_flags && ARRAY['SOURCE_RECORD_CONFLICT']::text[])"""
                active_at = as_of or datetime.now(UTC)
                active_params = (
                    projection["projection_version_id"],
                    active_at,
                    active_at,
                    active_at,
                )
                counts = conn.execute(
                    f"""SELECT count(*) AS total_count,
                               count(*) FILTER (WHERE j.eligibility = 'ELIGIBLE')
                                   AS eligible_count,
                               count(*) FILTER (WHERE j.eligibility = 'CONDITIONAL')
                                   AS conditional_count
                        FROM c_compute.matching_job j
                        {active_join}
                        WHERE j.recommendation_snapshot_id = %s""",
                    (*active_params, snapshot_id),
                ).fetchone()
                header.update(dict(counts))
                found_current_ids, current_ids = self._read_current_job_ids(
                    header.get("result_payload")
                )
                if not found_current_ids:
                    legacy_ids = conn.execute(
                        "SELECT payload ? 'current_job_ids' AS has_current_job_ids, "
                        "payload -> 'current_job_ids' AS current_job_ids "
                        "FROM c_compute.snapshot WHERE snapshot_id = %s",
                        (snapshot_id,),
                    ).fetchone()
                    _, current_ids = self._read_current_job_ids(
                        self._legacy_current_job_ids_payload(legacy_ids)
                    )
                if current_ids is not None:
                    header["active_current_count"] = len(
                        self._active_job_ids(
                            conn,
                            current_ids,
                            as_of=active_at,
                            projection_version_id=projection["projection_version_id"],
                        )
                    )
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
                           j.assessment_hash,
                           CASE WHEN j.job_fact_id IS NULL THEN legacy_source.payload
                                WHEN fact_source.job_fact_id IS NOT NULL
                                THEN fact_source.payload
                                WHEN legacy_source.job_fact_id = j.job_fact_id
                                THEN legacy_source.payload END AS source,
                           CASE WHEN j.job_fact_id IS NULL
                                THEN legacy_source.source_hash
                                WHEN fact_source.job_fact_id IS NOT NULL
                                THEN fact_source.source_hash
                                WHEN legacy_source.job_fact_id = j.job_fact_id
                                THEN legacy_source.source_hash END AS source_hash,
                           j.job_fact_id AS assessment_job_fact_id,
                           CASE WHEN j.job_fact_id IS NULL
                                THEN legacy_source.job_fact_id
                                WHEN fact_source.job_fact_id IS NOT NULL
                                THEN fact_source.job_fact_id
                                WHEN legacy_source.job_fact_id = j.job_fact_id
                                THEN legacy_source.job_fact_id END AS source_job_fact_id
                    FROM (
                        SELECT j.job_id, j.eligibility, j.assessment,
                               j.assessment_hash, j.cohort_snapshot_id, j.position,
                               j.job_fact_id
                        FROM c_compute.matching_job
                        j {active_join}
                        WHERE recommendation_snapshot_id = %s {eligibility_sql}
                        ORDER BY position LIMIT %s OFFSET %s
                    ) j
                    LEFT JOIN c_compute.matching_source_fact fact_source
                      ON fact_source.cohort_snapshot_id = j.cohort_snapshot_id
                     AND fact_source.job_id = j.job_id
                     AND fact_source.job_fact_id = j.job_fact_id
                    LEFT JOIN c_compute.matching_source legacy_source
                      ON legacy_source.cohort_snapshot_id = j.cohort_snapshot_id
                     AND legacy_source.job_id = j.job_id
                    ORDER BY j.position""",
                (*active_params, snapshot_id, limit + 1, offset),
            ).fetchall()
            has_next = len(rows) > limit
            return {
                **header,
                "items": self._restore_matching_rows(rows[:limit]),
                "has_next": has_next,
            }

    @staticmethod
    def _read_current_job_ids(payload: Any) -> tuple[bool, list[str] | None]:
        if not isinstance(payload, dict) or "current_job_ids" not in payload:
            return False, None
        current_ids = payload["current_job_ids"]
        if not isinstance(current_ids, list) or not all(
            isinstance(job_id, str) for job_id in current_ids
        ):
            raise StoredMatchingIntegrityError(
                "stored current_job_ids must be an array of strings"
            )
        return True, current_ids

    @staticmethod
    def _legacy_current_job_ids_payload(row: Mapping[str, Any] | None) -> dict | None:
        if row is None or not row["has_current_job_ids"]:
            return None
        return {"current_job_ids": row["current_job_ids"]}

    def get_matching_detail(
        self,
        snapshot_id: str,
        *,
        owner: str,
        job_id: str,
        active_only: bool = False,
        as_of: datetime | None = None,
    ) -> dict | None:
        with self._connect() as conn:
            header = self._matching_header(
                conn, snapshot_id, owner, compare_projection=active_only
            )
            if header is None or header["status"] != "READY":
                return header
            active_join = ""
            active_params: tuple[Any, ...] = ()
            if active_only:
                projection = conn.execute(
                    "SELECT projection_version_id FROM c_compute.job_projection_head "
                    "WHERE stream = 'JOB_SEARCH'"
                ).fetchone()
                if projection is None:
                    raise LookupError("projection head unavailable")
                active_at = as_of or datetime.now(UTC)
                active_join = """JOIN c_compute.job_projection_job active
                    ON active.projection_version_id = %s
                   AND active.job_key = j.job_id
                   AND active.posting_status <> 'CLOSED'
                   AND (active.deadline IS NULL OR active.deadline > %s)
                   AND active.collected_at <= %s
                   AND (active.posted_at IS NULL OR active.posted_at <= %s)
                   AND active.body_status = 'TEXT_AVAILABLE'
                   AND NOT (active.quality_flags && ARRAY['SOURCE_RECORD_CONFLICT']::text[])"""
                active_params = (
                    projection["projection_version_id"],
                    active_at,
                    active_at,
                    active_at,
                )
            row = conn.execute(
                f"""SELECT j.job_id, j.eligibility, j.assessment,
                          j.assessment_hash,
                          CASE WHEN j.job_fact_id IS NULL THEN legacy_source.payload
                               WHEN fact_source.job_fact_id IS NOT NULL
                               THEN fact_source.payload
                               WHEN legacy_source.job_fact_id = j.job_fact_id
                               THEN legacy_source.payload END AS source,
                          CASE WHEN j.job_fact_id IS NULL
                               THEN legacy_source.source_hash
                               WHEN fact_source.job_fact_id IS NOT NULL
                               THEN fact_source.source_hash
                               WHEN legacy_source.job_fact_id = j.job_fact_id
                               THEN legacy_source.source_hash END AS source_hash,
                          j.job_fact_id AS assessment_job_fact_id,
                          CASE WHEN j.job_fact_id IS NULL
                               THEN legacy_source.job_fact_id
                               WHEN fact_source.job_fact_id IS NOT NULL
                               THEN fact_source.job_fact_id
                               WHEN legacy_source.job_fact_id = j.job_fact_id
                               THEN legacy_source.job_fact_id END AS source_job_fact_id
                   FROM c_compute.matching_job j
                   {active_join}
                   LEFT JOIN c_compute.matching_source_fact fact_source
                     ON fact_source.cohort_snapshot_id = j.cohort_snapshot_id
                    AND fact_source.job_id = j.job_id
                    AND fact_source.job_fact_id = j.job_fact_id
                   LEFT JOIN c_compute.matching_source legacy_source
                     ON legacy_source.cohort_snapshot_id = j.cohort_snapshot_id
                    AND legacy_source.job_id = j.job_id
                   WHERE j.recommendation_snapshot_id = %s AND j.job_id = %s""",
                (*active_params, snapshot_id, job_id),
            ).fetchone()
            return {
                **header,
                "item": self._restore_matching_rows([row])[0] if row else None,
            }

    @staticmethod
    def _active_job_ids(
        conn,
        job_ids,
        *,
        as_of: datetime,
        projection_version_id: str,
    ) -> frozenset[str]:
        requested = tuple(dict.fromkeys(job_ids))
        if not requested:
            return frozenset()
        rows = conn.execute(
            """SELECT job_key
               FROM c_compute.job_projection_job
               WHERE projection_version_id = %s
                 AND job_key = ANY(%s)
                 AND posting_status <> 'CLOSED'
                 AND (deadline IS NULL OR deadline > %s)
                 AND collected_at <= %s
                 AND (posted_at IS NULL OR posted_at <= %s)
                 AND body_status = 'TEXT_AVAILABLE'
                 AND NOT (quality_flags && ARRAY['SOURCE_RECORD_CONFLICT']::text[])""",
            (projection_version_id, list(requested), as_of, as_of, as_of),
        ).fetchall()
        return frozenset(row["job_key"] for row in rows)

    def get_active_job_ids(
        self, job_ids, *, as_of: datetime | None = None
    ) -> frozenset[str]:
        with self._connect() as conn:
            projection = conn.execute(
                "SELECT projection_version_id FROM c_compute.job_projection_head "
                "WHERE stream = 'JOB_SEARCH'"
            ).fetchone()
            if projection is None:
                raise LookupError("projection head unavailable")
            return self._active_job_ids(
                conn,
                job_ids,
                as_of=as_of or datetime.now(UTC),
                projection_version_id=projection["projection_version_id"],
            )

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

    def get_trend_periods(self, *, source: str, granularity: str) -> list[str]:
        """List the periods this source actually published, oldest first.

        조회하는 쪽이 "최근 주차"를 달력으로 계산하면 게시되지 않은 주를 묻게 되고,
        그러면 값이 있는데도 빈 카드가 뜬다. 어느 기간이 있는지는 저장한 쪽이 안다.

        화면의 기간 이동도 이 목록을 쓴다(S15P21E102-329). 목록이 없으면 이전/다음
        버튼이 어디로 갈지 알 수 없어 기능 자체가 성립하지 않는다.

        오름순인 것은 기존 navigation 계약이다 — `model/periodRows`가 "기간은 오름순이고
        마지막이 제일 최신"이라고 고정했고, 카드는 `periods[index - 1]`을 이전으로 읽는다.
        기간 문자열은 정렬 가능한 형식이라(`2026-08`, `2026-09-07`) 같은 granularity
        안에서는 사전순이 곧 시간순이다.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """WITH heads AS MATERIALIZED (
                       SELECT s.payload
                       FROM c_compute.head h
                       JOIN c_compute.snapshot s ON s.snapshot_id = h.snapshot_id
                       WHERE h.kind = 'TREND'
                         AND h.owner = ''
                         AND s.kind = 'TREND'
                         AND s.payload->>'source' = %(source)s
                   )
                   SELECT DISTINCT p->>'period' AS period
                   FROM heads, jsonb_array_elements(heads.payload->'points') p
                   WHERE p->>'granularity' = %(granularity)s
                     AND p->>%(value_key)s IS NOT NULL
                   ORDER BY period ASC""",
                {
                    "source": source,
                    "granularity": granularity,
                    "value_key": TREND_VALUE_KEYS[source],
                },
            ).fetchall()
        return [row["period"] for row in rows if row["period"]]

    def get_trend_rankings(
        self, *, source: str, granularity: str, period: str, limit: int
    ) -> list[dict[str, Any]]:
        """Rank one period's technologies from the stored Trend heads.

        <h2>Why this reads the stored result instead of recomputing</h2>

        The numbers already exist. Each technology keeps a TREND head per source
        and the payload carries the per-period points, so a ranking is a sort of
        what is on disk -- not a new measurement. Asking the compute path again
        would produce the same values at a much higher cost.

        <h2>Which head speaks for a technology</h2>

        A technology has several heads for one source because the stream identity
        includes the published `periods` tuple, and the same period appears in
        more than one publication. They agree today, but "they happen to agree"
        is not a rule. The rule is the head that observed last, and the stream
        breaks a tie so the answer never depends on row order.

        Only heads that actually carry the requested period compete. Picking the
        newest head first and then looking for the period would drop a technology
        whose latest publication covers a different span.

        <h2>Which value ranks</h2>

        `TREND_VALUE_KEYS` 가 고른 필드다 — GH Archive 는 `active_repo_count`. 같은
        point 의 `event_count` 로 정렬하면 순위가 "많이 쓰이는 기술"이 아니라 "바쁜
        저장소에 같이 들어 있는 기술"이 된다. 분모(`TREND_DENOMINATOR_KEYS`)를 함께
        돌려주는 것은 주차마다 코호트 크기가 달라 raw count 를 기간끼리 비교할 수 없기
        때문이다. 비율은 여기서 만들지 않는다 — 저장된 값이 아닌 것을 저장물인 척
        돌려주지 않는다.

        <h2>Which rows are rankable</h2>

        A row needs a value. The quality verdict rides along untouched so the
        caller can say the sample is thin -- see S15P21E102-327. What is filtered
        here is the absence of a measurement, not a weak one.

        <h2>Why the head set is materialized</h2>

        Written as one flat join the planner expanded every stored payload before
        the source filter narrowed anything, and the read took 18s against
        production -- past the statement timeout, so the endpoint simply failed.
        Narrowing the heads first and only then walking their points returns the
        same rows in about 160ms.
        """
        if limit < 1 or limit > 100:
            raise ValueError("invalid ranking limit")
        with self._connect() as conn:
            rows = conn.execute(
                """WITH heads AS MATERIALIZED (
                       SELECT h.stream, h.occurred_at, s.payload
                       FROM c_compute.head h
                       JOIN c_compute.snapshot s ON s.snapshot_id = h.snapshot_id
                       WHERE h.kind = 'TREND'
                         AND h.owner = ''
                         AND s.kind = 'TREND'
                         AND s.payload->>'source' = %(source)s
                   ),
                   candidate AS (
                       SELECT heads.payload->>'tech_id' AS tech_id,
                              (p->>%(value_key)s)::bigint AS value,
                              (p->>%(denominator_key)s)::bigint AS denominator,
                              p->>'status' AS data_status,
                              row_number() OVER (
                                  PARTITION BY heads.payload->>'tech_id'
                                  ORDER BY heads.occurred_at DESC, heads.stream DESC
                              ) AS pick
                       FROM heads, jsonb_array_elements(heads.payload->'points') p
                       WHERE p->>'granularity' = %(granularity)s
                         AND p->>'period' = %(period)s
                         AND p->>%(value_key)s IS NOT NULL
                   )
                   SELECT tech_id, value, denominator, data_status
                   FROM candidate
                   WHERE pick = 1
                   ORDER BY value DESC, tech_id ASC
                   LIMIT %(limit)s""",
                {
                    "source": source,
                    "granularity": granularity,
                    "period": period,
                    "value_key": TREND_VALUE_KEYS[source],
                    "denominator_key": TREND_DENOMINATOR_KEYS[source],
                    "limit": limit,
                },
            ).fetchall()
        return [dict(row) for row in rows]

    def get_trend_values(
        self,
        *,
        source: str,
        granularity: str,
        period: str,
        tech_ids: tuple[str, ...],
    ) -> dict[str, int]:
        """Read one period's ranking value for a bounded set of technologies.

        <h2>왜 순위 조회를 재사용하지 않는가</h2>

        `get_trend_rankings` 는 모집단 전체에서 상위 N 개를 돌려준다. 추천 후보가
        그 N 안에 없으면 "값이 없다"와 "상위 N 에 없다"가 구분되지 않고, 그러면
        측정된 기술이 미측정으로 읽힌다. 여기서는 물어본 기술만 정확히 답한다.

        <h2>왜 기술마다 부르지 않는가</h2>

        후보 수만큼 질의하면 추천 한 건이 왕복을 세 번 한다. `tech_id` 를 배열로
        넘겨 한 질의로 끝낸다 -- `get_head_snapshots` 와 같은 bounded-set 방식이다.

        <h2>어떤 head 가 그 기술을 대표하는가</h2>

        `get_trend_rankings` 와 같은 규칙이다. stream identity 에 게시 `periods` 가
        들어가 한 기술이 한 출처에 여러 head 를 가지므로, 요청한 기간을 **실제로
        담은** head 중 마지막으로 관측된 것을 쓰고 stream 으로 동률을 깬다. 값이
        없는 point 는 제외하되 얇은 표본은 제외하지 않는다(S15P21E102-327) --
        `INSUFFICIENT_DATA` 라도 값이 있으면 순위에 쓸 수 있다.

        값 필드는 `TREND_VALUE_KEYS` 가 고른다. GH Archive 는 `active_repo_count`
        이며 같은 point 의 `event_count` 는 여기서도 쓰지 않는다.
        """
        if not tech_ids:
            return {}
        if len(tech_ids) > 10 or len(tech_ids) != len(set(tech_ids)):
            raise ValueError("invalid trend value selection")
        with self._connect() as conn:
            rows = conn.execute(
                """WITH heads AS MATERIALIZED (
                       SELECT h.stream, h.occurred_at, s.payload
                       FROM c_compute.head h
                       JOIN c_compute.snapshot s ON s.snapshot_id = h.snapshot_id
                       WHERE h.kind = 'TREND'
                         AND h.owner = ''
                         AND s.kind = 'TREND'
                         AND s.payload->>'source' = %(source)s
                         AND s.payload->>'tech_id' = ANY(%(tech_ids)s)
                   ),
                   candidate AS (
                       SELECT heads.payload->>'tech_id' AS tech_id,
                              (p->>%(value_key)s)::bigint AS value,
                              row_number() OVER (
                                  PARTITION BY heads.payload->>'tech_id'
                                  ORDER BY heads.occurred_at DESC, heads.stream DESC
                              ) AS pick
                       FROM heads, jsonb_array_elements(heads.payload->'points') p
                       WHERE p->>'granularity' = %(granularity)s
                         AND p->>'period' = %(period)s
                         AND p->>%(value_key)s IS NOT NULL
                   )
                   SELECT tech_id, value
                   FROM candidate
                   WHERE pick = 1""",
                {
                    "source": source,
                    "granularity": granularity,
                    "period": period,
                    "tech_ids": list(tech_ids),
                    "value_key": TREND_VALUE_KEYS[source],
                },
            ).fetchall()
        return {row["tech_id"]: int(row["value"]) for row in rows}

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
