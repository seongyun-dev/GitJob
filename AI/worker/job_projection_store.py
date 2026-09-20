"""Atomic PostgreSQL publication for immutable job search projections."""

from __future__ import annotations

import logging
import time
import unicodedata
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from job.cohort import CohortCriteria, CohortPurpose, CohortStatus
from job.demand import DemandSnapshot
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
    build_projection_cohort,
    canonical_hash,
)

LOGGER = logging.getLogger(__name__)


class JobProjectionIntegrityError(RuntimeError):
    """A deterministic projection disagrees with already persisted content."""


class JobProjectionSidecarNotReady(LookupError):
    """The pinned published version predates the SQL summary sidecars."""


_SUMMARY_SQL = """
WITH base AS (
    SELECT j.*, m.raw_region_identity, m.raw_career_identity,
           m.market_required_tech_ids, m.market_preferred_tech_ids
      FROM c_compute.job_projection_job j
      JOIN c_compute.job_projection_market_job m
        ON m.projection_version_id = j.projection_version_id
       AND m.job_key = j.job_key
     WHERE j.projection_version_id = %(version_id)s
), decisions AS (
    SELECT base.*,
           (%(sources)s::text[] <> '{}' AND
            NOT source_site = ANY(%(sources)s::text[])) AS source_bad,
           (%(target_role)s::text IS NOT NULL AND
            NOT role_codes @> ARRAY[%(target_role)s::text]) AS role_bad,
           (posting_status = 'CLOSED' AND %(active_scope)s) AS status_bad,
           (deadline IS NOT NULL AND deadline <= %(as_of)s AND
            %(active_scope)s) AS deadline_bad,
           (collected_at > %(as_of)s) AS collected_bad,
           (posted_at IS NOT NULL AND posted_at > %(as_of)s) AS posted_future,
           ((%(posted_from)s::timestamptz IS NOT NULL OR
             %(posted_to)s::timestamptz IS NOT NULL) AND posted_at IS NULL)
               AS posted_review,
           ((%(posted_from)s::timestamptz IS NOT NULL AND posted_at IS NOT NULL
             AND posted_at < %(posted_from)s) OR
            (%(posted_to)s::timestamptz IS NOT NULL AND posted_at IS NOT NULL
             AND posted_at >= %(posted_to)s)) AS period_bad,
           CASE
             WHEN NOT %(has_regions)s OR %(region_all)s THEN 0
             WHEN raw_region_identity = ANY(%(raw_regions)s::text[]) THEN 0
             WHEN region_state = 'NATIONWIDE' THEN 0
             WHEN region_codes && %(region_codes)s::text[] THEN 0
             WHEN region_state = 'UNKNOWN' OR %(region_filter_unknown)s THEN 1
             ELSE 2
           END AS region_decision,
           CASE
             WHEN NOT %(has_careers)s THEN 0
             WHEN raw_career_identity = ANY(%(raw_careers)s::text[]) THEN 0
             WHEN career_codes && %(career_codes)s::text[] THEN 0
             WHEN %(career_filter_unknown)s THEN 1
             WHEN career_state = 'UNRESTRICTED' THEN 0
             WHEN career_state IN ('UNKNOWN', 'AMBIGUOUS') THEN 1
             ELSE 2
           END AS career_decision
      FROM base
), flags AS (
    SELECT decisions.*,
           (source_bad OR role_bad OR status_bad OR deadline_bad OR
            collected_bad OR posted_future OR period_bad OR
            region_decision = 2 OR career_decision = 2) AS excluded,
           (cardinality(quality_flags) > 0 OR posted_review OR
            region_decision = 1 OR career_decision = 1) AS review
      FROM decisions
), scoped AS (
    SELECT flags.*,
           CASE
             WHEN %(purpose)s = 'ACTIVE_MATCHING' THEN
               NOT excluded AND NOT (quality_flags &&
                   ARRAY['BODY_UNAVAILABLE','SOURCE_RECORD_CONFLICT']::text[])
             WHEN %(purpose)s = 'CURRENT_MARKET' THEN NOT excluded
             ELSE NOT excluded AND NOT review
           END AS selected,
           NOT excluded AND NOT review AS strict
      FROM flags
), candidate_scope AS (
    SELECT c.left_job_key, c.right_job_key
      FROM c_compute.job_projection_market_candidate c
      JOIN scoped l ON l.job_key = c.left_job_key AND l.selected
      JOIN scoped r ON r.job_key = c.right_job_key AND r.selected
     WHERE c.projection_version_id = %(version_id)s
), candidate_fanout AS (
    SELECT candidate_scope.*,
           count(*) OVER (PARTITION BY left_job_key) AS left_fanout,
           count(*) OVER (PARTITION BY right_job_key) AS right_fanout
      FROM candidate_scope
), pair_map AS (
    SELECT left_job_key AS job_key,
           jsonb_build_array('pair', left_job_key, right_job_key)::text
             AS posting_identity
      FROM candidate_fanout WHERE left_fanout = 1 AND right_fanout = 1
    UNION ALL
    SELECT right_job_key AS job_key,
           jsonb_build_array('pair', left_job_key, right_job_key)::text
             AS posting_identity
      FROM candidate_fanout WHERE left_fanout = 1 AND right_fanout = 1
), identified AS (
    SELECT s.*, CASE WHEN %(purpose)s = 'CURRENT_MARKET'
                         THEN COALESCE(p.posting_identity,
                              jsonb_build_array('single', s.job_key)::text)
                         ELSE jsonb_build_array('single', s.job_key)::text
                     END AS posting_identity
      FROM scoped s LEFT JOIN pair_map p ON p.job_key = s.job_key
), summary AS (
    SELECT count(DISTINCT posting_identity) FILTER (WHERE selected) AS denominator,
           count(*) FILTER (WHERE excluded) AS excluded_count,
           count(*) FILTER (WHERE NOT excluded AND review) AS review_count,
           count(*) FILTER (WHERE selected) AS selected_row_count,
           count(*) FILTER (WHERE selected AND strict) -
             count(DISTINCT posting_identity) FILTER (WHERE selected AND strict)
               AS cross_site_merged_count
      FROM identified
), category_rows AS (
    SELECT i.posting_identity, technology.tech_id, technology.category
      FROM identified i
      CROSS JOIN LATERAL (
          SELECT unnest(CASE WHEN %(purpose)s = 'CURRENT_MARKET'
                             THEN i.market_required_tech_ids
                             ELSE i.required_tech_ids END), 'required'
          UNION ALL
          SELECT unnest(CASE WHEN %(purpose)s = 'CURRENT_MARKET'
                             THEN i.market_preferred_tech_ids
                             ELSE i.preferred_tech_ids END), 'preferred'
          UNION ALL
          SELECT unnest(CASE WHEN %(purpose)s = 'CURRENT_MARKET' OR NOT i.strict
                             THEN '{}'::text[] ELSE i.general_tech_ids END), 'general'
      ) AS technology(tech_id, category)
     WHERE i.selected
), technology_counts AS (
    SELECT tech_id,
           count(DISTINCT posting_identity) FILTER
             (WHERE category='required')::integer AS required_count,
           count(DISTINCT posting_identity) FILTER
             (WHERE category='preferred')::integer AS preferred_count,
           count(DISTINCT posting_identity) FILTER
             (WHERE category='general')::integer AS general_count,
           count(DISTINCT posting_identity)::integer AS total_count
      FROM category_rows GROUP BY tech_id
), ranked AS (
    SELECT technology_counts.*,
           row_number() OVER (ORDER BY total_count DESC, tech_id)::integer AS rank,
           CASE WHEN required_count > 0 THEN row_number() OVER
             (ORDER BY required_count DESC, tech_id)::integer END AS required_rank,
           CASE WHEN preferred_count > 0 THEN row_number() OVER
             (ORDER BY preferred_count DESC, tech_id)::integer END AS preferred_rank,
           CASE WHEN general_count > 0 THEN row_number() OVER
             (ORDER BY general_count DESC, tech_id)::integer END AS general_rank
      FROM technology_counts
)
SELECT s.*,
       COALESCE((
         SELECT jsonb_agg(jsonb_build_object(
           'tech_id', tech_id,
           'required_count', required_count,
           'preferred_count', preferred_count,
           'general_count', general_count,
           'total_count', total_count,
           'required_ratio', required_count::float8 / NULLIF(s.denominator, 0),
           'preferred_ratio', preferred_count::float8 / NULLIF(s.denominator, 0),
           'general_ratio', general_count::float8 / NULLIF(s.denominator, 0),
           'total_ratio', total_count::float8 / NULLIF(s.denominator, 0),
           'rank', rank,
           'required_rank', required_rank,
           'preferred_rank', preferred_rank,
           'general_rank', general_rank,
           'total_rank', rank
         ) ORDER BY rank)
         FROM ranked
       ), '[]'::jsonb) AS technologies
  FROM summary s
"""

_SELECTED_KEYS_SQL = (
    _SUMMARY_SQL.partition("), candidate_scope AS (")[0]
    + ")\nSELECT job_key FROM scoped WHERE selected ORDER BY job_key"
)


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
                    cursor.executemany(
                        """INSERT INTO c_compute.job_projection_market_job
                           (projection_version_id, job_key, normalized_company,
                            normalized_title, market_region_identity,
                            raw_region_identity, raw_career_identity,
                            market_required_tech_ids, market_preferred_tech_ids)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        [
                            (
                                item.projection_version_id,
                                item.job_key,
                                item.normalized_company,
                                item.normalized_title,
                                item.market_region_identity,
                                item.raw_region_identity,
                                item.raw_career_identity,
                                list(item.market_required_tech_ids),
                                list(item.market_preferred_tech_ids),
                            )
                            for item in projection.market_jobs
                        ],
                    )
                    cursor.executemany(
                        """INSERT INTO c_compute.job_projection_market_candidate
                           (projection_version_id, left_job_key, right_job_key)
                           VALUES (%s, %s, %s)""",
                        [
                            (
                                item.projection_version_id,
                                item.left_job_key,
                                item.right_job_key,
                            )
                            for item in projection.market_candidates
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
                market_validation = conn.execute(
                    """SELECT
                           (SELECT count(*)
                              FROM c_compute.job_projection_market_job
                             WHERE projection_version_id = %s) AS market_job_count,
                           (SELECT count(*)
                              FROM c_compute.job_projection_market_candidate
                             WHERE projection_version_id = %s) AS candidate_count""",
                    (
                        projection.projection_version_id,
                        projection.projection_version_id,
                    ),
                ).fetchone()
                persisted_candidates = conn.execute(
                    """SELECT left_job_key, right_job_key
                         FROM c_compute.job_projection_market_candidate
                        WHERE projection_version_id = %s
                        ORDER BY left_job_key, right_job_key""",
                    (projection.projection_version_id,),
                ).fetchall()
                candidate_hash = canonical_hash(
                    [
                        [row["left_job_key"], row["right_job_key"]]
                        for row in persisted_candidates
                    ]
                )
                if (
                    market_validation["market_job_count"] != len(projection.jobs)
                    or market_validation["candidate_count"]
                    != len(projection.market_candidates)
                    or candidate_hash
                    != projection.build_stats.get("market_candidate_hash")
                ):
                    raise JobProjectionIntegrityError(
                        "projection market sidecar validation failed"
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
            region_all = any(
                normalize_region(value)[1] is RegionState.NATIONWIDE
                for value in criteria.regions
            )
            if criteria.regions and not region_unknown and not region_all:
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
            market_jobs=(),
            market_candidates=(),
            build_stats=stats,
        )
        return aggregate_projection_demand(projection, criteria)

    def summary(
        self,
        criteria: CohortCriteria,
        *,
        projection_version_id: str | None = None,
    ) -> DemandSnapshot:
        """Aggregate a Preview from typed rows without loading fact payloads."""

        criteria = CohortCriteria.model_validate_json(criteria.model_dump_json())
        connect_started = time.perf_counter()
        conn = self._connect()
        connect_duration_ms = (time.perf_counter() - connect_started) * 1000
        query_started = time.perf_counter()
        with conn:
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
            coverage = conn.execute(
                """SELECT count(*) AS count
                     FROM c_compute.job_projection_market_job
                    WHERE projection_version_id = %s""",
                (version["projection_version_id"],),
            ).fetchone()["count"]
            if coverage != version["job_count"]:
                raise JobProjectionSidecarNotReady(
                    "published job projection market sidecar is unavailable"
                )
            params = _criteria_params(criteria, version)
            row = conn.execute(_SUMMARY_SQL, params).fetchone()
        query_duration_ms = (time.perf_counter() - query_started) * 1000
        if row is None:
            raise JobProjectionIntegrityError("projection summary returned no row")
        denominator = int(row["denominator"] or 0)
        LOGGER.info(
            "projection_summary_completed projection_version_id=%s purpose=%s "
            "denominator=%s connect_duration_ms=%.3f query_duration_ms=%.3f",
            version["projection_version_id"],
            criteria.purpose.value,
            denominator,
            connect_duration_ms,
            query_duration_ms,
        )
        build_stats = dict(version["build_stats"])
        return DemandSnapshot(
            cohort_id="projection-cohort-"
            + canonical_hash(
                {
                    "projection_version_id": version["projection_version_id"],
                    "criteria": criteria.model_dump(mode="json"),
                }
            ),
            status=CohortStatus.for_size(denominator, criteria.min_jobs),
            criteria=criteria,
            denominator=denominator,
            matching_count=(
                denominator
                if criteria.purpose is CohortPurpose.ACTIVE_MATCHING
                else None
            ),
            input_count=version["job_count"],
            duplicate_count=0,
            excluded_count=int(row["excluded_count"] or 0),
            review_count=int(row["review_count"] or 0),
            cross_site_merged_count=(
                int(row["cross_site_merged_count"] or 0)
                if criteria.purpose is CohortPurpose.CURRENT_MARKET
                else 0
            ),
            dataset_snapshot_id=version["input_union_id"],
            pipeline_run_id=str(
                build_stats.get("pipeline_run_id", "job-projection")
            ),
            collector_version=str(
                build_stats.get("collector_version", "job-search-projection/v1")
            ),
            registry_version=version["registry_version"],
            parser_version=version["parser_version"],
            quality_version=version["quality_version"],
            aggregation_version=version["aggregation_version"],
            projection_version_id=version["projection_version_id"],
            technologies=tuple(row["technologies"]),
        )

    def selected_job_keys(
        self,
        criteria: CohortCriteria,
        *,
        projection_version_id: str,
    ) -> tuple[str, ...]:
        """Return typed-row selector identities for bounded shadow comparison."""

        criteria = CohortCriteria.model_validate_json(criteria.model_dump_json())
        with self._connect() as conn:
            version = conn.execute(
                """SELECT * FROM c_compute.job_projection_version
                   WHERE projection_version_id = %s AND state = 'PUBLISHED'""",
                (projection_version_id,),
            ).fetchone()
            if version is None:
                raise LookupError("published job projection version is unavailable")
            coverage = conn.execute(
                """SELECT count(*) AS count
                     FROM c_compute.job_projection_market_job
                    WHERE projection_version_id = %s""",
                (projection_version_id,),
            ).fetchone()["count"]
            if coverage != version["job_count"]:
                raise JobProjectionSidecarNotReady(
                    "published job projection market sidecar is unavailable"
                )
            return tuple(
                row["job_key"]
                for row in conn.execute(
                    _SELECTED_KEYS_SQL, _criteria_params(criteria, version)
                ).fetchall()
            )

    def cohort(
        self,
        criteria: CohortCriteria,
        *,
        projection_version_id: str,
    ) -> ProjectionDemandResult:
        """Restore only SQL-selected facts for one explicitly pinned version."""

        criteria = CohortCriteria.model_validate_json(criteria.model_dump_json())
        with self._connect() as conn:
            version = conn.execute(
                """SELECT * FROM c_compute.job_projection_version
                   WHERE projection_version_id = %s AND state = 'PUBLISHED'""",
                (projection_version_id,),
            ).fetchone()
            if version is None:
                raise LookupError("published job projection version is unavailable")
            coverage = conn.execute(
                """SELECT count(*) AS count
                     FROM c_compute.job_projection_market_job
                    WHERE projection_version_id = %s""",
                (projection_version_id,),
            ).fetchone()["count"]
            if coverage != version["job_count"]:
                raise JobProjectionSidecarNotReady(
                    "published job projection market sidecar is unavailable"
                )
            params = _criteria_params(criteria, version)
            selected_keys = tuple(
                row["job_key"]
                for row in conn.execute(_SELECTED_KEYS_SQL, params).fetchall()
            )
            rows = (
                conn.execute(
                    """SELECT j.*, f.schema_version, f.job_key AS fact_job_key,
                              f.source_site AS fact_source_site, f.source_posting_id,
                              f.content_hash,
                              f.registry_version AS fact_registry_version,
                              f.parser_version AS fact_parser_version,
                              f.requirements_version AS fact_requirements_version,
                              f.payload, f.payload_hash
                       FROM c_compute.job_projection_job j
                       JOIN c_compute.job_fact f ON f.job_fact_id = j.job_fact_id
                       WHERE j.projection_version_id = %s
                         AND j.job_key = ANY(%s::text[])
                       ORDER BY j.job_key""",
                    (projection_version_id, list(selected_keys)),
                ).fetchall()
                if selected_keys
                else []
            )
        facts: list[JobFact] = []
        jobs: list[ProjectionJob] = []
        if tuple(row["job_key"] for row in rows) != selected_keys:
            raise JobProjectionIntegrityError(
                "selected projection jobs were not restored exactly"
            )
        for row in rows:
            if (
                row["projection_version_id"] != projection_version_id
                or row["fact_job_key"] != row["job_key"]
                or row["fact_source_site"] != row["source_site"]
            ):
                raise JobProjectionIntegrityError(
                    "job fact identity disagrees with the pinned projection"
                )
            if (
                row["fact_registry_version"] != version["registry_version"]
                or row["fact_parser_version"] != version["parser_version"]
                or row["fact_requirements_version"]
                != version["requirements_version"]
            ):
                raise JobProjectionIntegrityError(
                    "job fact versions disagree with the pinned projection"
                )
            if canonical_hash(row["payload"]) != row["payload_hash"]:
                raise JobProjectionIntegrityError("job fact payload hash disagrees")
            facts.append(
                JobFact(
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
            )
            jobs.append(_projection_job(row))
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
            facts=tuple(facts),
            jobs=tuple(jobs),
            market_jobs=(),
            market_candidates=(),
            build_stats=dict(version["build_stats"]),
        )
        snapshot = self.summary(
            criteria, projection_version_id=projection_version_id
        )
        cohort = build_projection_cohort(projection, criteria).model_copy(
            update={"cohort_id": snapshot.cohort_id}
        )
        return ProjectionDemandResult(
            snapshot=snapshot,
            selected_job_ids=selected_keys,
            cohort=cohort,
        )

    def readiness(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT v.projection_version_id, v.observed_at, v.job_count,
                          v.build_stats,
                          count(j.job_key) AS stored_job_count,
                          count(m.job_key) AS market_job_count,
                          count(j.job_key) FILTER (WHERE f.job_fact_id IS NULL) AS missing_fact_count,
                          extract(epoch FROM (clock_timestamp() - v.observed_at))::bigint AS lag_seconds
                   FROM c_compute.job_projection_head h
                   JOIN c_compute.job_projection_version v
                     ON v.projection_version_id = h.projection_version_id
                    AND v.state = 'PUBLISHED'
                   LEFT JOIN c_compute.job_projection_job j
                     ON j.projection_version_id = v.projection_version_id
                   LEFT JOIN c_compute.job_fact f ON f.job_fact_id = j.job_fact_id
                   LEFT JOIN c_compute.job_projection_market_job m
                     ON m.projection_version_id = j.projection_version_id
                    AND m.job_key = j.job_key
                   WHERE h.stream = 'JOB_SEARCH'
                   GROUP BY v.projection_version_id, v.observed_at, v.job_count,
                            v.build_stats"""
            ).fetchone()
            candidate_rows = (
                []
                if row is None
                else conn.execute(
                    """SELECT left_job_key, right_job_key
                         FROM c_compute.job_projection_market_candidate
                        WHERE projection_version_id = %s
                        ORDER BY left_job_key, right_job_key""",
                    (row["projection_version_id"],),
                ).fetchall()
            )
        if row is None:
            return {"status": "NOT_PUBLISHED"}
        ready = (
            row["stored_job_count"] == row["job_count"]
            and row["missing_fact_count"] == 0
        )
        expected_market_count = dict(row["build_stats"]).get("market_job_count")
        expected_candidate_count = dict(row["build_stats"]).get(
            "market_candidate_count"
        )
        expected_candidate_hash = dict(row["build_stats"]).get(
            "market_candidate_hash"
        )
        candidate_hash = canonical_hash(
            [
                [candidate["left_job_key"], candidate["right_job_key"]]
                for candidate in candidate_rows
            ]
        )
        market_ready = (
            expected_market_count == row["job_count"]
            and row["market_job_count"] == row["job_count"]
            and expected_candidate_count == len(candidate_rows)
            and expected_candidate_hash == candidate_hash
        )
        return {
            "status": "READY" if ready else "INTEGRITY_FAILED",
            **dict(row),
            "market_sql_ready": market_ready,
            "market_candidate_count": len(candidate_rows),
            "market_candidate_hash": candidate_hash,
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


def _raw_identity(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _criteria_params(criteria: CohortCriteria, version) -> dict[str, Any]:
    region_codes, region_unknown = _normalized_filter_codes(
        criteria.regions, normalize_region, RegionState.UNKNOWN
    )
    region_all = any(
        normalize_region(value)[1] is RegionState.NATIONWIDE
        for value in criteria.regions
    )
    career_codes, career_unknown = _normalized_filter_codes(
        criteria.career_levels,
        normalize_career_level,
        {CareerState.UNKNOWN, CareerState.AMBIGUOUS},
    )
    return {
        "version_id": version["projection_version_id"],
        "sources": list(criteria.sources),
        "target_role": criteria.target_role,
        "active_scope": criteria.purpose
        in {CohortPurpose.ACTIVE_MATCHING, CohortPurpose.CURRENT_MARKET},
        "as_of": criteria.as_of,
        "posted_from": criteria.posted_from,
        "posted_to": criteria.posted_to,
        "has_regions": bool(criteria.regions),
        "region_all": region_all,
        "raw_regions": [_raw_identity(value) for value in criteria.regions],
        "region_codes": region_codes,
        "region_filter_unknown": region_unknown,
        "has_careers": bool(criteria.career_levels),
        "raw_careers": [_raw_identity(value) for value in criteria.career_levels],
        "career_codes": career_codes,
        "career_filter_unknown": career_unknown,
        "purpose": criteria.purpose.value,
    }


def _projection_job(row) -> ProjectionJob:
    return ProjectionJob(
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
