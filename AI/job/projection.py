"""Deterministic search facts built from the already verified input union."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from job.classifier import (
    JobClassificationBatch,
    JobClassificationRecord,
    MatchStatus,
    RequirementClass,
)
from job.cohort import (
    JOB_QUALITY_VERSION,
    SUPPORTED_JOB_ROLES,
    CohortCriteria,
    CohortPurpose,
    CohortStatus,
    JobCohort,
    PreparedCohortBatch,
    PreparedCohortRecord,
    _matching_required_clauses,
    build_cohort_from_prepared,
    matches_role,
)
from job.contracts import BodyStatus, JobAnalysisInputBatch, JobPostingInput
from job.cross_site_identity import canonical_identities
from job.demand import (
    JOB_DEMAND_AGGREGATION_VERSION,
    DemandSnapshot,
    _demand_rows,
)
from job.eligibility import (
    CareerState,
    FilterMatch,
    RegionState,
    match_career_level,
    match_region,
    normalize_career_level,
    normalize_region,
)
from job.input_union import PreparedInputUnion
from job.requirements import JOB_REQUIREMENTS_SCHEMA_VERSION, JobRequirements

JOB_FACT_SCHEMA_VERSION = "job-fact/v1"
JOB_PROJECTION_SCHEMA_VERSION = "job-search-projection/v1"


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _sorted(values) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


@dataclass(frozen=True)
class JobFact:
    job_fact_id: str
    schema_version: str
    job_key: str
    source_site: str
    source_posting_id: str
    content_hash: str
    registry_version: str
    parser_version: str
    requirements_version: str
    payload: dict[str, Any]
    payload_hash: str


@dataclass(frozen=True)
class ProjectionJob:
    projection_version_id: str
    job_key: str
    job_fact_id: str
    source_site: str
    role_codes: tuple[str, ...]
    region_codes: tuple[str, ...]
    region_state: str
    career_codes: tuple[str, ...]
    career_state: str
    posting_status: str
    body_status: str
    posted_at: datetime | None
    deadline: datetime | None
    collected_at: datetime
    required_tech_ids: tuple[str, ...]
    preferred_tech_ids: tuple[str, ...]
    general_tech_ids: tuple[str, ...]
    quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class JobProjection:
    projection_version_id: str
    input_union_id: str
    input_signature: str
    registry_version: str
    parser_version: str
    quality_version: str
    requirements_version: str
    aggregation_version: str
    observed_at: datetime
    facts: tuple[JobFact, ...]
    jobs: tuple[ProjectionJob, ...]
    build_stats: dict[str, Any]


def _classified_tech_ids(item, requirement_class: RequirementClass) -> tuple[str, ...]:
    return _sorted(
        technology.tech_id
        for technology in item.classification.technologies
        if technology.tech_id is not None
        and technology.match_status is MatchStatus.MATCHED
        and technology.requirement_class is requirement_class
    )


def _requirement_tech_ids(clauses) -> tuple[str, ...]:
    return _sorted(tech_id for clause in clauses for tech_id in clause.tech_ids)


def materialize_job_projection(prepared: PreparedInputUnion) -> JobProjection:
    """Materialize once; never rerun classification or requirement extraction."""

    cohort = prepared.cohort
    provenance = prepared.provenance
    if any(item.requirements is None for item in cohort.records):
        raise ValueError("prepared union must include active requirement results")

    input_payload = provenance.model_dump(mode="json")
    input_signature = canonical_hash(input_payload)
    version_identity = {
        "schema_version": JOB_PROJECTION_SCHEMA_VERSION,
        "input_signature": input_signature,
        "registry_version": cohort.classified.registry_version,
        "parser_version": cohort.classified.parser_version,
        "quality_version": JOB_QUALITY_VERSION,
        "requirements_version": JOB_REQUIREMENTS_SCHEMA_VERSION,
        "aggregation_version": JOB_DEMAND_AGGREGATION_VERSION,
    }
    projection_version_id = "jp-" + canonical_hash(version_identity)

    facts: list[JobFact] = []
    candidates: dict[str, list[tuple[str, JobFact, Any]]] = {}
    for item in cohort.records:
        record = item.record
        requirements = item.requirements
        assert requirements is not None
        source_site = record.source_site.strip().upper()
        job_key = f"{source_site}:{record.source_posting_id}"
        payload = {
            "record": record.model_dump(
                mode="json", exclude={"description_text", "technology_mentions"}
            ),
            "classification": item.classification.model_dump(mode="json"),
            "requirements": requirements.model_dump(mode="json"),
            "prepared_digest": item.digest,
        }
        payload_hash = canonical_hash(payload)
        fact_identity = {
            "schema_version": JOB_FACT_SCHEMA_VERSION,
            "job_key": job_key,
            "content_hash": record.content_hash,
            "registry_version": cohort.classified.registry_version,
            "parser_version": cohort.classified.parser_version,
            "requirements_version": requirements.schema_version,
            "payload_hash": payload_hash,
        }
        fact = JobFact(
            job_fact_id=canonical_hash(fact_identity),
            schema_version=JOB_FACT_SCHEMA_VERSION,
            job_key=job_key,
            source_site=source_site,
            source_posting_id=record.source_posting_id,
            content_hash=record.content_hash,
            registry_version=cohort.classified.registry_version,
            parser_version=cohort.classified.parser_version,
            requirements_version=requirements.schema_version,
            payload=payload,
            payload_hash=payload_hash,
        )
        facts.append(fact)
        candidates.setdefault(job_key, []).append((item.digest, fact, item))

    jobs: list[ProjectionJob] = []
    body_unavailable = posting_unknown = region_unknown = career_unknown = 0
    for job_key, variants in sorted(candidates.items()):
        _, fact, item = min(variants, key=lambda value: value[0])
        record = item.record
        requirements = item.requirements
        assert requirements is not None
        region_codes, region_state = normalize_region(record.region)
        career_codes, career_state = normalize_career_level(record.career_level)
        flags: set[str] = set()
        if record.body_status.value != "TEXT_AVAILABLE":
            flags.add("BODY_UNAVAILABLE")
            body_unavailable += 1
        if record.posting_status.value == "UNKNOWN":
            flags.add("POSTING_STATUS_UNKNOWN")
            posting_unknown += 1
        if region_state.value == "UNKNOWN":
            region_unknown += 1
        if career_state.value in {"UNKNOWN", "AMBIGUOUS"}:
            career_unknown += 1
        if (
            len(variants) > 1
            or (record.source_site.strip().upper(), record.source_posting_id)
            in prepared.conflicting_keys
        ):
            flags.add("SOURCE_RECORD_CONFLICT")
        _, requirement_reasons = _matching_required_clauses(
            requirements, item.classification
        )
        flags.update(requirement_reasons)
        jobs.append(
            ProjectionJob(
                projection_version_id=projection_version_id,
                job_key=job_key,
                job_fact_id=fact.job_fact_id,
                source_site=fact.source_site,
                role_codes=_sorted(
                    role for role in SUPPORTED_JOB_ROLES if matches_role(record, role)
                ),
                region_codes=region_codes,
                region_state=region_state.value,
                career_codes=career_codes,
                career_state=career_state.value,
                posting_status=record.posting_status.value,
                body_status=record.body_status.value,
                posted_at=record.posted_at,
                deadline=record.deadline,
                collected_at=record.collected_at,
                required_tech_ids=_requirement_tech_ids(requirements.required),
                preferred_tech_ids=_requirement_tech_ids(requirements.preferred),
                general_tech_ids=_classified_tech_ids(item, RequirementClass.SKILL),
                quality_flags=_sorted(flags),
            )
        )

    observed_at = max(
        (batch.collected_at for batch in provenance.input_batches),
        default=datetime.fromtimestamp(0, tz=UTC),
    )
    source_counts = {
        source: sum(job.source_site == source for job in jobs)
        for source in sorted({job.source_site for job in jobs})
    }
    unique_facts = {fact.job_fact_id: fact for fact in facts}
    stats = {
        "pipeline_run_id": cohort.batch.pipeline_run_id,
        "collector_version": cohort.batch.collector_version,
        "input_record_count": provenance.input_record_count,
        "selected_record_count": provenance.selected_record_count,
        "conflict_record_count": provenance.conflict_record_count,
        "duplicate_record_count": provenance.duplicate_record_count,
        "superseded_record_count": provenance.superseded_record_count,
        "projection_job_count": len(jobs),
        "fact_count": len(unique_facts),
        "body_unavailable_count": body_unavailable,
        "posting_status_unknown_count": posting_unknown,
        "region_unknown_count": region_unknown,
        "career_unknown_count": career_unknown,
        "active_job_count": sum(job.posting_status == "ACTIVE" for job in jobs),
        "closed_job_count": sum(job.posting_status == "CLOSED" for job in jobs),
        "unknown_status_job_count": sum(
            job.posting_status == "UNKNOWN" for job in jobs
        ),
        "deadline_expired_job_count": sum(
            job.deadline is not None and job.deadline <= observed_at for job in jobs
        ),
        "source_job_counts": source_counts,
        "source_input_states": {
            source: "COMPLETE"
            for source in sorted(
                {batch.source_site for batch in provenance.input_batches}
            )
        },
    }
    return JobProjection(
        projection_version_id=projection_version_id,
        input_union_id=cohort.batch.dataset_snapshot_id,
        input_signature=input_signature,
        registry_version=cohort.classified.registry_version,
        parser_version=cohort.classified.parser_version,
        quality_version=JOB_QUALITY_VERSION,
        requirements_version=JOB_REQUIREMENTS_SCHEMA_VERSION,
        aggregation_version=JOB_DEMAND_AGGREGATION_VERSION,
        observed_at=observed_at,
        facts=tuple(sorted(unique_facts.values(), key=lambda item: item.job_fact_id)),
        jobs=tuple(jobs),
        build_stats=stats,
    )


@dataclass(frozen=True)
class ProjectionDemandResult:
    snapshot: DemandSnapshot
    selected_job_ids: tuple[str, ...]
    cohort: JobCohort


def build_projection_cohort(
    projection: JobProjection, criteria: CohortCriteria
) -> JobCohort:
    """Restore active personalized inputs from immutable facts without reparsing."""

    facts_by_id = {fact.job_fact_id: fact for fact in projection.facts}
    prepared_rows = []
    posting_rows = []
    classification_rows = []
    conflicts: set[str] = set()
    for projection_job in projection.jobs:
        fact = facts_by_id.get(projection_job.job_fact_id)
        if fact is None:
            raise ValueError("projection job references a missing immutable fact")
        record_payload = dict(fact.payload["record"])
        if record_payload.get("body_status") == BodyStatus.TEXT_AVAILABLE.value:
            record_payload["description_text"] = "prepared"
        record_payload["technology_mentions"] = []
        record = JobPostingInput.model_validate(record_payload)
        classification = JobClassificationRecord.model_validate(
            fact.payload["classification"]
        )
        requirements = JobRequirements.model_validate(fact.payload["requirements"])
        prepared_digest = str(fact.payload["prepared_digest"])
        prepared_rows.append(
            PreparedCohortRecord(
                digest=prepared_digest,
                record=record,
                classification=classification,
                requirements=requirements,
            )
        )
        posting_rows.append(record)
        classification_rows.append(classification)
        if "SOURCE_RECORD_CONFLICT" in projection_job.quality_flags:
            conflicts.add(prepared_digest)

    pipeline_run_id = str(
        projection.build_stats.get("pipeline_run_id", "job-projection")
    )
    collector_version = str(
        projection.build_stats.get("collector_version", JOB_PROJECTION_SCHEMA_VERSION)
    )
    batch = JobAnalysisInputBatch(
        schema_version="job-analysis-input/v1",
        dataset_snapshot_id=projection.input_union_id,
        pipeline_run_id=pipeline_run_id,
        collector_version=collector_version,
        records=tuple(posting_rows),
    )
    classified = JobClassificationBatch(
        schema_version="job-technology-classification/v1",
        input_schema_version="job-analysis-input/v1",
        dataset_snapshot_id=projection.input_union_id,
        pipeline_run_id=pipeline_run_id,
        collector_version=collector_version,
        registry_version=projection.registry_version,
        parser_version=projection.parser_version,
        records=tuple(classification_rows),
    )
    return build_cohort_from_prepared(
        PreparedCohortBatch(
            batch=batch,
            classified=classified,
            records=tuple(prepared_rows),
            conflicts=frozenset(conflicts),
            qualify_job_ids=True,
            input_count=len(prepared_rows),
        ),
        criteria,
    )


def _allowed_region_codes(values: tuple[str, ...]) -> tuple[set[str], bool, bool]:
    codes: set[str] = set()
    nationwide = False
    unknown = False
    for value in values:
        normalized, state = normalize_region(value)
        codes.update(normalized)
        nationwide = nationwide or state is RegionState.NATIONWIDE
        unknown = unknown or state is RegionState.UNKNOWN
    return codes, nationwide, unknown


def _allowed_career_codes(values: tuple[str, ...]) -> tuple[set[str], bool]:
    codes: set[str] = set()
    ambiguous = False
    for value in values:
        normalized, state = normalize_career_level(value)
        codes.update(normalized)
        ambiguous = ambiguous or state in {CareerState.AMBIGUOUS, CareerState.UNKNOWN}
    return codes, ambiguous


def _fact_records(projection: JobProjection) -> dict[str, dict[str, Any]]:
    return {fact.job_fact_id: fact.payload["record"] for fact in projection.facts}


def aggregate_projection_demand(
    projection: JobProjection, criteria: CohortCriteria
) -> ProjectionDemandResult:
    """Aggregate persisted attributes without classification or requirement parsing."""

    criteria = CohortCriteria.model_validate_json(criteria.model_dump_json())
    fact_by_id = {fact.job_fact_id: fact for fact in projection.facts}
    records = _fact_records(projection)
    allowed_regions, region_all, region_filter_unknown = _allowed_region_codes(
        criteria.regions
    )
    allowed_careers, career_filter_unknown = _allowed_career_codes(
        criteria.career_levels
    )
    selected: list[ProjectionJob] = []
    strict_ids: set[str] = set()
    excluded_count = int(projection.build_stats.get("prefilter_excluded_count", 0))
    review_count = 0
    for job in projection.jobs:
        excluded: set[str] = set()
        review = set(job.quality_flags)
        if criteria.sources and job.source_site not in criteria.sources:
            excluded.add("SOURCE_NOT_MATCHED")
        if (
            criteria.target_role is not None
            and criteria.target_role not in job.role_codes
        ):
            excluded.add("ROLE_NOT_MATCHED")
        if job.posting_status == "CLOSED" and criteria.purpose in {
            CohortPurpose.ACTIVE_MATCHING,
            CohortPurpose.CURRENT_MARKET,
        }:
            excluded.add("POSTING_CLOSED")
        if (
            criteria.purpose
            in {CohortPurpose.ACTIVE_MATCHING, CohortPurpose.CURRENT_MARKET}
            and job.deadline is not None
            and job.deadline <= criteria.as_of
        ):
            excluded.add("DEADLINE_PASSED")
        if job.collected_at > criteria.as_of:
            excluded.add("COLLECTED_AFTER_AS_OF")
        if job.posted_at is not None and job.posted_at > criteria.as_of:
            excluded.add("POSTED_AFTER_AS_OF")
        if criteria.posted_from or criteria.posted_to:
            if job.posted_at is None:
                review.add("POSTED_AT_UNKNOWN")
            elif (criteria.posted_from and job.posted_at < criteria.posted_from) or (
                criteria.posted_to and job.posted_at >= criteria.posted_to
            ):
                excluded.add("OUTSIDE_POSTED_PERIOD")
        if criteria.regions and not region_all:
            if region_filter_unknown:
                region_match = match_region(
                    records[job.job_fact_id].get("region"), criteria.regions
                )
                if region_match is FilterMatch.UNKNOWN:
                    review.add("REGION_UNKNOWN")
                elif region_match is FilterMatch.NOT_MATCHED:
                    excluded.add("REGION_NOT_MATCHED")
            elif job.region_state == "UNKNOWN":
                review.add("REGION_UNKNOWN")
            elif job.region_state != "NATIONWIDE" and not (
                set(job.region_codes) & allowed_regions
            ):
                excluded.add("REGION_NOT_MATCHED")
        if criteria.career_levels:
            if career_filter_unknown:
                career_match = match_career_level(
                    records[job.job_fact_id].get("career_level"),
                    criteria.career_levels,
                )
                if career_match is FilterMatch.UNKNOWN:
                    review.add("CAREER_LEVEL_UNKNOWN")
                elif career_match is FilterMatch.NOT_MATCHED:
                    excluded.add("CAREER_LEVEL_NOT_MATCHED")
            elif job.career_state in {"UNKNOWN", "AMBIGUOUS"}:
                review.add("CAREER_LEVEL_UNKNOWN")
            elif job.career_state != "UNRESTRICTED" and not (
                set(job.career_codes) & allowed_careers
            ):
                excluded.add("CAREER_LEVEL_NOT_MATCHED")

        matching = not excluded
        if criteria.purpose is CohortPurpose.ACTIVE_MATCHING and {
            "BODY_UNAVAILABLE",
            "SOURCE_RECORD_CONFLICT",
        }.intersection(review):
            matching = False
        if criteria.purpose is CohortPurpose.CURRENT_MARKET:
            # Quality/review rows remain in the market denominator; only scope and
            # active-status failures are removed.
            matching = not excluded.intersection(
                {
                    "SOURCE_NOT_MATCHED",
                    "REGION_NOT_MATCHED",
                    "CAREER_LEVEL_NOT_MATCHED",
                    "COLLECTED_AFTER_AS_OF",
                    "POSTED_AFTER_AS_OF",
                    "POSTING_CLOSED",
                    "DEADLINE_PASSED",
                }
            )
        elif criteria.purpose is not CohortPurpose.ACTIVE_MATCHING:
            matching = not excluded and not review
        if matching:
            selected.append(job)
        if excluded:
            excluded_count += 1
        elif review:
            review_count += 1
        else:
            strict_ids.add(job.job_key)

    identity_by_job = {job.job_key: job.job_key for job in selected}
    cross_site_merged_count = 0
    if criteria.purpose is CohortPurpose.CURRENT_MARKET:
        rows = []
        for job in selected:
            record = records[job.job_fact_id]
            rows.append(
                SimpleNamespace(
                    source_site=job.source_site,
                    source_posting_id=record["source_posting_id"],
                    company_name=record["company_name"],
                    title=record["title"],
                    region=record.get("region"),
                    deadline=job.deadline,
                )
            )
        canonical = canonical_identities(rows)
        for job in selected:
            record = records[job.job_fact_id]
            identity_by_job[job.job_key] = canonical.get(
                (job.source_site, record["source_posting_id"]), job.job_key
            )
        strict_selected = [job for job in selected if job.job_key in strict_ids]
        cross_site_merged_count = len(strict_selected) - len(
            {identity_by_job[job.job_key] for job in strict_selected}
        )

    counts: dict[str, dict[str, set[str]]] = {}
    for job in selected:
        fact = fact_by_id[job.job_fact_id]
        if criteria.purpose is CohortPurpose.CURRENT_MARKET:
            categories = {"required": set(), "preferred": set(), "general": set()}
            for technology in fact.payload["classification"]["technologies"]:
                tech_id = technology.get("tech_id")
                if not tech_id or technology.get("match_status") != "MATCHED":
                    continue
                requirement_class = technology.get("requirement_class")
                if requirement_class == "REQUIRED":
                    categories["required"].add(tech_id)
                elif requirement_class == "PREFERRED":
                    categories["preferred"].add(tech_id)
        else:
            categories = {
                "required": set(job.required_tech_ids),
                "preferred": set(job.preferred_tech_ids),
                "general": (
                    set(job.general_tech_ids) if job.job_key in strict_ids else set()
                ),
            }
        posting_id = identity_by_job[job.job_key]
        for category, tech_ids in categories.items():
            for tech_id in tech_ids:
                bucket = counts.setdefault(
                    tech_id,
                    {
                        name: set()
                        for name in ("required", "preferred", "general", "total")
                    },
                )
                bucket[category].add(posting_id)
                bucket["total"].add(posting_id)

    denominator = len(set(identity_by_job.values()))
    input_count = int(
        projection.build_stats.get("projection_job_count", len(projection.jobs))
    )
    status = CohortStatus.for_size(denominator, criteria.min_jobs)
    snapshot = DemandSnapshot(
        cohort_id="projection-cohort-"
        + canonical_hash(
            {
                "projection_version_id": projection.projection_version_id,
                "criteria": criteria.model_dump(mode="json"),
            }
        ),
        status=status,
        criteria=criteria,
        denominator=denominator,
        matching_count=(
            denominator if criteria.purpose is CohortPurpose.ACTIVE_MATCHING else None
        ),
        input_count=input_count,
        duplicate_count=0,
        excluded_count=excluded_count,
        review_count=review_count,
        cross_site_merged_count=cross_site_merged_count,
        dataset_snapshot_id=projection.input_union_id,
        pipeline_run_id=str(
            projection.build_stats.get("pipeline_run_id", "job-projection")
        ),
        collector_version=str(
            projection.build_stats.get(
                "collector_version", JOB_PROJECTION_SCHEMA_VERSION
            )
        ),
        registry_version=projection.registry_version,
        parser_version=projection.parser_version,
        quality_version=projection.quality_version,
        aggregation_version=projection.aggregation_version,
        projection_version_id=projection.projection_version_id,
        technologies=_demand_rows(counts, denominator) if denominator else (),
    )
    return ProjectionDemandResult(
        snapshot=snapshot,
        selected_job_ids=tuple(sorted(job.job_key for job in selected)),
        cohort=build_projection_cohort(projection, criteria),
    )
