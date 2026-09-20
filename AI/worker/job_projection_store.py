"""Atomic PostgreSQL publication for immutable job search projections."""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from job.cohort import CohortCriteria, CohortPurpose
from job.eligibility import (
    CareerState,
    RegionState,
    normalize_career_level,
    normalize_region,
)
from job.projection import (
    JobFact,
    JobProjection,
    ProjectionDemandResult,
    ProjectionJob,
    aggregate_projection_demand,
    canonical_hash,
)

LOGGER = logging.getLogger(__name__)


class JobProjectionIntegrityError(RuntimeError):
    """A deterministic projection disagrees with already persisted content."""


class JobProjectionStore:
    def __init__(self, dsn: str):
        self._dsn = dsn

    def _connect(self):
        return psycopg.connect(
            self._dsn,
            connect_timeout=5,
            row_factory=dict_row,
            options="-c statement_timeout=30000 -c lock_timeout=5000",
        )

    def publish(self, projection: JobProjection) -> str:
        """Publish all rows and swap JOB_SEARCH head in one transaction."""

        started = time.perf_counter()
        try:
            with self._connect() as conn:
                existing = conn.execute(
                    "SELECT state, input_signature FROM c_compute.job_projection_version "
                    "WHERE projection_version_id = %s FOR UPDATE",
                    (projection.projection_version_id,),
                ).fetchone()
                if (
                    existing
                    and existing["input_signature"] != projection.input_signature
                ):
                    raise JobProjectionIntegrityError("projection identity was reused")
                if existing and existing["state"] == "PUBLISHED":
                    LOGGER.info(
                        "projection_publish_reused projection_version_id=%s "
                        "projection_state=PUBLISHED projection_job_count=%s",
                        projection.projection_version_id,
                        len(projection.jobs),
                    )
                    return projection.projection_version_id
                if existing:
                    conn.execute(
                        "DELETE FROM c_compute.job_projection_version "
                        "WHERE projection_version_id = %s AND state = 'FAILED'",
                        (projection.projection_version_id,),
                    )
                conn.execute(
                    """INSERT INTO c_compute.job_projection_version
                       (projection_version_id, state, input_union_id, input_signature,
                        registry_version, parser_version, quality_version,
                        requirements_version, aggregation_version, observed_at,
                        job_count, build_stats)
                       VALUES (%s, 'BUILDING', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        projection.projection_version_id,
                        projection.input_union_id,
                        projection.input_signature,
                        projection.registry_version,
                        projection.parser_version,
                        projection.quality_version,
                        projection.requirements_version,
                        projection.aggregation_version,
                        projection.observed_at,
                        len(projection.jobs),
                        Jsonb(projection.build_stats),
                    ),
                )
                existing_facts = conn.execute(
                    "SELECT count(*) AS count FROM c_compute.job_fact "
                    "WHERE job_fact_id = ANY(%s)",
                    ([item.job_fact_id for item in projection.facts],),
                ).fetchone()["count"]
                with conn.cursor() as cursor:
                    cursor.executemany(
                        """INSERT INTO c_compute.job_fact
                           (job_fact_id, schema_version, job_key, source_site,
                            source_posting_id, content_hash, registry_version,
                            parser_version, requirements_version, payload, payload_hash)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (job_fact_id) DO NOTHING""",
                        [
                            (
                                item.job_fact_id,
                                item.schema_version,
                                item.job_key,
                                item.source_site,
                                item.source_posting_id,
                                item.content_hash,
                                item.registry_version,
                                item.parser_version,
                                item.requirements_version,
                                Jsonb(item.payload),
                                item.payload_hash,
                            )
                            for item in projection.facts
                        ],
                    )
                facts = conn.execute(
                    "SELECT job_fact_id, payload_hash FROM c_compute.job_fact "
                    "WHERE job_fact_id = ANY(%s)",
                    ([item.job_fact_id for item in projection.facts],),
                ).fetchall()
                expected_facts = {
                    item.job_fact_id: item.payload_hash for item in projection.facts
                }
                if {
                    row["job_fact_id"]: row["payload_hash"] for row in facts
                } != expected_facts:
                    raise JobProjectionIntegrityError("persisted facts disagree")
                with conn.cursor() as cursor:
                    cursor.executemany(
                        """INSERT INTO c_compute.job_projection_job
                           (projection_version_id, job_key, job_fact_id, source_site,
                            role_codes, region_codes, region_state, career_codes,
                            career_state, posting_status, body_status, posted_at,
                            deadline, collected_at, required_tech_ids,
                            preferred_tech_ids, general_tech_ids, quality_flags)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                   %s, %s, %s, %s, %s, %s, %s)""",
                        [
                            (
                                item.projection_version_id,
                                item.job_key,
                                item.job_fact_id,
                                item.source_site,
                                list(item.role_codes),
                                list(item.region_codes),
                                item.region_state,
                                list(item.career_codes),
                                item.career_state,
                                item.posting_status,
                                item.body_status,
                                item.posted_at,
                                item.deadline,
                                item.collected_at,
                                list(item.required_tech_ids),
                                list(item.preferred_tech_ids),
                                list(item.general_tech_ids),
                                list(item.quality_flags),
                            )
                            for item in projection.jobs
                        ],
                    )
                row = conn.execute(
                    """SELECT count(*) AS count,
                              count(DISTINCT job_key) AS unique_count,
                              count(*) FILTER (WHERE role_codes <> c_compute.array_sort_distinct(role_codes)
                                OR region_codes <> c_compute.array_sort_distinct(region_codes)
                                OR career_codes <> c_compute.array_sort_distinct(career_codes)
                                OR required_tech_ids <> c_compute.array_sort_distinct(required_tech_ids)
                                OR preferred_tech_ids <> c_compute.array_sort_distinct(preferred_tech_ids)
                                OR general_tech_ids <> c_compute.array_sort_distinct(general_tech_ids)
                                OR quality_flags <> c_compute.array_sort_distinct(quality_flags)) AS invalid_count
                       FROM c_compute.job_projection_job
                       WHERE projection_version_id = %s""",
                    (projection.projection_version_id,),
                ).fetchone()
                if (
                    row["count"] != len(projection.jobs)
                    or row["unique_count"] != len(projection.jobs)
                    or row["invalid_count"]
                ):
                    raise JobProjectionIntegrityError(
                        "projection row validation failed"
                    )
                publish_stats = {
                    **projection.build_stats,
                    "projection_fact_inserted": len(projection.facts)
                    - existing_facts,
                    "projection_fact_reused": existing_facts,
                    "projection_publish_duration_ms": round(
                        (time.perf_counter() - started) * 1000, 3
                    ),
                }
                conn.execute(
                    """UPDATE c_compute.job_projection_version
                       SET state = 'PUBLISHED', published_at = clock_timestamp(),
                           build_stats = %s
                       WHERE projection_version_id = %s AND state = 'BUILDING'""",
                    (Jsonb(publish_stats), projection.projection_version_id),
                )
                conn.execute("SELECT pg_advisory_xact_lock(331030)")
                blocked = conn.execute(
                    "SELECT 1 FROM c_compute.job_projection_block "
                    "WHERE projection_version_id = %s",
                    (projection.projection_version_id,),
                ).fetchone()
                if blocked is not None:
                    raise JobProjectionIntegrityError("projection version is blocked")
                conn.execute(
                    """INSERT INTO c_compute.job_projection_head
                       (stream, projection_version_id, observed_at, updated_at)
                       VALUES ('JOB_SEARCH', %s, %s, clock_timestamp())
                       ON CONFLICT (stream) DO UPDATE
                       SET projection_version_id = EXCLUDED.projection_version_id,
                           observed_at = EXCLUDED.observed_at,
                           updated_at = EXCLUDED.updated_at
                       WHERE (EXCLUDED.observed_at, EXCLUDED.projection_version_id) >
                             (c_compute.job_projection_head.observed_at,
                              c_compute.job_projection_head.projection_version_id)""",
                    (projection.projection_version_id, projection.observed_at),
                )
            LOGGER.info(
                "projection_publish_completed projection_version_id=%s "
                "projection_state=PUBLISHED projection_publish_duration_ms=%.3f "
                "projection_job_count=%s projection_fact_inserted=%s "
                "projection_fact_reused=%s",
                projection.projection_version_id,
                (time.perf_counter() - started) * 1000,
                len(projection.jobs),
                len(projection.facts) - existing_facts,
                existing_facts,
            )
            return projection.projection_version_id
        except Exception as exc:
            LOGGER.error(
                "projection_build_failed projection_version_id=%s "
                "projection_state=FAILED projection_build_failure_reason=%s",
                projection.projection_version_id,
                type(exc).__name__,
            )
            self._record_failure(projection, type(exc).__name__.upper()[:64])
            raise

    def rollback(
        self,
        *,
        expected_current: str,
        target_projection_version_id: str,
        actor: str,
        reason: str,
    ) -> str:
        """CAS rollback with an audit row and a block on the rejected version."""

        if not actor.strip() or not reason.strip():
            raise ValueError("rollback actor and reason are required")
        with self._connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(331030)")
            current = conn.execute(
                """SELECT h.projection_version_id
                   FROM c_compute.job_projection_head h
                   WHERE h.stream = 'JOB_SEARCH' FOR UPDATE"""
            ).fetchone()
            if current is None or current["projection_version_id"] != expected_current:
                raise JobProjectionIntegrityError("projection rollback CAS failed")
            blocked_target = conn.execute(
                "SELECT 1 FROM c_compute.job_projection_block "
                "WHERE projection_version_id = %s",
                (target_projection_version_id,),
            ).fetchone()
            if blocked_target is not None:
                raise JobProjectionIntegrityError("rollback target is blocked")
            target = conn.execute(
                """SELECT v.projection_version_id, v.observed_at, v.job_count,
                          count(j.job_key) AS stored_job_count,
                          count(j.job_key) FILTER (WHERE f.job_fact_id IS NULL)
                              AS missing_fact_count
                   FROM c_compute.job_projection_version v
                   LEFT JOIN c_compute.job_projection_job j
                     ON j.projection_version_id = v.projection_version_id
                   LEFT JOIN c_compute.job_fact f ON f.job_fact_id = j.job_fact_id
                   WHERE v.projection_version_id = %s AND v.state = 'PUBLISHED'
                   GROUP BY v.projection_version_id""",
                (target_projection_version_id,),
            ).fetchone()
            if (
                target is None
                or target["job_count"] != target["stored_job_count"]
                or target["missing_fact_count"]
            ):
                raise JobProjectionIntegrityError("rollback target is not healthy")
            conn.execute(
                """INSERT INTO c_compute.job_projection_block
                   (projection_version_id, reason, actor)
                   VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
                (expected_current, reason.strip(), actor.strip()),
            )
            conn.execute(
                """INSERT INTO c_compute.job_projection_head_audit
                   (change_id, from_projection_version_id, to_projection_version_id,
                    actor, reason)
                   VALUES (%s, %s, %s, %s, %s)""",
                (
                    uuid4(),
                    expected_current,
                    target_projection_version_id,
                    actor.strip(),
                    reason.strip(),
                ),
            )
            conn.execute(
                """UPDATE c_compute.job_projection_head
                   SET projection_version_id = %s, observed_at = %s,
                       updated_at = clock_timestamp()
                   WHERE stream = 'JOB_SEARCH'""",
                (target_projection_version_id, target["observed_at"]),
            )
        return target_projection_version_id

    def _record_failure(self, projection: JobProjection, error_code: str) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO c_compute.job_projection_version
                       (projection_version_id, state, input_union_id, input_signature,
                        registry_version, parser_version, quality_version,
                        requirements_version, aggregation_version, observed_at,
                        job_count, build_stats, error_code)
                       VALUES (%s, 'FAILED', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (projection_version_id) DO UPDATE
                       SET state = 'FAILED', published_at = NULL,
                           error_code = EXCLUDED.error_code
                       WHERE c_compute.job_projection_version.state <> 'PUBLISHED'""",
                    (
                        projection.projection_version_id,
                        projection.input_union_id,
                        projection.input_signature,
                        projection.registry_version,
                        projection.parser_version,
                        projection.quality_version,
                        projection.requirements_version,
                        projection.aggregation_version,
                        projection.observed_at,
                        len(projection.jobs),
                        Jsonb(projection.build_stats),
                        error_code,
                    ),
                )
        except psycopg.Error:
            # The original build exception remains the actionable error, but a
            # failed audit write must still be visible to operators.
            LOGGER.exception("job_projection_failure_record_write_failed")

    def head(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            return conn.execute(
                """SELECT v.* FROM c_compute.job_projection_head h
                   JOIN c_compute.job_projection_version v
                     ON v.projection_version_id = h.projection_version_id
                   WHERE h.stream = 'JOB_SEARCH' AND v.state = 'PUBLISHED'"""
            ).fetchone()

    def demand(
        self,
        criteria: CohortCriteria,
        *,
        projection_version_id: str | None = None,
    ) -> ProjectionDemandResult:
        """Read one PUBLISHED version, pinning an expected identity when supplied."""

        clauses = ["j.projection_version_id = %s"]
        params: list[Any] = []
        with self._connect() as conn:
            version = (
                conn.execute(
                    """SELECT * FROM c_compute.job_projection_version
                       WHERE projection_version_id = %s AND state = 'PUBLISHED'""",
                    (projection_version_id,),
                ).fetchone()
                if projection_version_id is not None
                else conn.execute(
                    """SELECT v.* FROM c_compute.job_projection_head h
                       JOIN c_compute.job_projection_version v
                         ON v.projection_version_id = h.projection_version_id
                       WHERE h.stream = 'JOB_SEARCH' AND v.state = 'PUBLISHED'"""
                ).fetchone()
            )
            if version is None:
                raise LookupError("published job projection head is unavailable")
            params.append(version["projection_version_id"])
            if criteria.sources:
                clauses.append("j.source_site = ANY(%s)")
                params.append(list(criteria.sources))
            if criteria.target_role is not None:
                clauses.append("j.role_codes @> %s::text[]")
                params.append([criteria.target_role])
            if criteria.purpose in {
                CohortPurpose.ACTIVE_MATCHING,
                CohortPurpose.CURRENT_MARKET,
            }:
                clauses.extend(
                    [
                        "j.posting_status <> 'CLOSED'",
                        "(j.deadline IS NULL OR j.deadline > %s)",
                    ]
                )
                params.append(criteria.as_of)
            clauses.extend(
                [
                    "j.collected_at <= %s",
                    "(j.posted_at IS NULL OR j.posted_at <= %s)",
                ]
            )
            params.extend((criteria.as_of, criteria.as_of))
            if criteria.posted_from is not None:
                clauses.append("(j.posted_at IS NULL OR j.posted_at >= %s)")
                params.append(criteria.posted_from)
            if criteria.posted_to is not None:
                clauses.append("(j.posted_at IS NULL OR j.posted_at < %s)")
                params.append(criteria.posted_to)
            region_codes, region_unknown = _normalized_filter_codes(
                criteria.regions, normalize_region, RegionState.UNKNOWN
            )
            if criteria.regions and not region_unknown:
                clauses.append(
                    "(j.region_state IN ('UNKNOWN', 'NATIONWIDE') "
                    "OR j.region_codes && %s::text[])"
                )
                params.append(region_codes)
            career_codes, career_unknown = _normalized_filter_codes(
                criteria.career_levels,
                normalize_career_level,
                {CareerState.UNKNOWN, CareerState.AMBIGUOUS},
            )
            if criteria.career_levels and not career_unknown:
                clauses.append(
                    "(j.career_state IN ('UNKNOWN', 'AMBIGUOUS', 'UNRESTRICTED') "
                    "OR j.career_codes && %s::text[])"
                )
                params.append(career_codes)
            rows = conn.execute(
                """SELECT j.*, f.schema_version, f.source_posting_id,
                          f.content_hash, f.registry_version AS fact_registry_version,
                          f.parser_version AS fact_parser_version,
                          f.requirements_version AS fact_requirements_version,
                          f.payload, f.payload_hash
                   FROM c_compute.job_projection_job j
                   JOIN c_compute.job_fact f ON f.job_fact_id = j.job_fact_id
                   WHERE """
                + " AND ".join(clauses)
                + " ORDER BY j.job_key",
                params,
            ).fetchall()
        facts: dict[str, JobFact] = {}
        jobs = []
        for row in rows:
            if canonical_hash(row["payload"]) != row["payload_hash"]:
                raise JobProjectionIntegrityError("job fact payload hash disagrees")
            facts[row["job_fact_id"]] = JobFact(
                job_fact_id=row["job_fact_id"],
                schema_version=row["schema_version"],
                job_key=row["job_key"],
                source_site=row["source_site"],
                source_posting_id=row["source_posting_id"],
                content_hash=row["content_hash"],
                registry_version=row["fact_registry_version"],
                parser_version=row["fact_parser_version"],
                requirements_version=row["fact_requirements_version"],
                payload=row["payload"],
                payload_hash=row["payload_hash"],
            )
            jobs.append(
                ProjectionJob(
                    projection_version_id=row["projection_version_id"],
                    job_key=row["job_key"],
                    job_fact_id=row["job_fact_id"],
                    source_site=row["source_site"],
                    role_codes=tuple(row["role_codes"]),
                    region_codes=tuple(row["region_codes"]),
                    region_state=row["region_state"],
                    career_codes=tuple(row["career_codes"]),
                    career_state=row["career_state"],
                    posting_status=row["posting_status"],
                    body_status=row["body_status"],
                    posted_at=row["posted_at"],
                    deadline=row["deadline"],
                    collected_at=row["collected_at"],
                    required_tech_ids=tuple(row["required_tech_ids"]),
                    preferred_tech_ids=tuple(row["preferred_tech_ids"]),
                    general_tech_ids=tuple(row["general_tech_ids"]),
                    quality_flags=tuple(row["quality_flags"]),
                )
            )
        stats = dict(version["build_stats"])
        stats["prefilter_excluded_count"] = version["job_count"] - len(jobs)
        projection = JobProjection(
            projection_version_id=version["projection_version_id"],
            input_union_id=version["input_union_id"],
            input_signature=version["input_signature"],
            registry_version=version["registry_version"],
            parser_version=version["parser_version"],
            quality_version=version["quality_version"],
            requirements_version=version["requirements_version"],
            aggregation_version=version["aggregation_version"],
            observed_at=version["observed_at"],
            facts=tuple(facts.values()),
            jobs=tuple(jobs),
            build_stats=stats,
        )
        return aggregate_projection_demand(projection, criteria)

    def readiness(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT v.projection_version_id, v.observed_at, v.job_count,
                          count(j.job_key) AS stored_job_count,
                          count(j.job_key) FILTER (WHERE f.job_fact_id IS NULL) AS missing_fact_count,
                          extract(epoch FROM (clock_timestamp() - v.observed_at))::bigint AS lag_seconds
                   FROM c_compute.job_projection_head h
                   JOIN c_compute.job_projection_version v
                     ON v.projection_version_id = h.projection_version_id
                    AND v.state = 'PUBLISHED'
                   LEFT JOIN c_compute.job_projection_job j
                     ON j.projection_version_id = v.projection_version_id
                   LEFT JOIN c_compute.job_fact f ON f.job_fact_id = j.job_fact_id
                   WHERE h.stream = 'JOB_SEARCH'
                   GROUP BY v.projection_version_id, v.observed_at, v.job_count"""
            ).fetchone()
        if row is None:
            return {"status": "NOT_PUBLISHED"}
        ready = (
            row["stored_job_count"] == row["job_count"]
            and row["missing_fact_count"] == 0
        )
        return {
            "status": "READY" if ready else "INTEGRITY_FAILED",
            **dict(row),
        }


def _normalized_filter_codes(values, normalizer, unknown_states):
    unknown_states = (
        unknown_states if isinstance(unknown_states, set) else {unknown_states}
    )
    codes: set[str] = set()
    unknown = False
    for value in values:
        normalized, state = normalizer(value)
        codes.update(normalized)
        unknown = unknown or state in unknown_states
    return sorted(codes), unknown
