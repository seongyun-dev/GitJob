"""Deterministic next-technology candidates and one-technology job deltas."""

import json
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import Field, StrictInt, field_validator, model_validator

from job.cohort import CohortJob, CohortPurpose, CohortStatus, JobCohort
from job.demand import DemandSnapshot, TechnologyDemand, aggregate_demand
from recommendation.evidence import (
    HELD_POLICY_VERSION,
    EvidenceAnalysis,
    EvidenceModel,
    GapSnapshot,
    HeldPolicyVersion,
    HeldStatus,
    HeldTechnologySelection,
    LegacyGapSnapshot,
    LegacyHeldTechnologySelection,
    NonBlank,
    build_gap,
    consume_evidence,
)
from registry.contracts import TechId

RECOMMENDATION_ALGORITHM_VERSION = "c-recommendation/lexicographic/v2"
PREREQUISITE_POLICY_VERSION = "c-learning-prerequisites/v1"
TIE_BREAK_RULE = "prerequisites-ready,gain-desc,required-count-desc,uncertainty-asc,total-count-desc,tech-id-asc"


class PrerequisiteRule(EvidenceModel):
    tech_id: TechId
    required_tech_ids: tuple[TechId, ...]
    fact_ids: tuple[NonBlank, ...] = Field(min_length=1)

    @field_validator("required_tech_ids", "fact_ids")
    @classmethod
    def canonicalize_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def forbid_self_requirement(self) -> "PrerequisiteRule":
        if self.tech_id in self.required_tech_ids:
            raise ValueError("technology cannot be its own prerequisite")
        return self


class PrerequisiteSnapshot(EvidenceModel):
    version: NonBlank
    rules: tuple[PrerequisiteRule, ...]

    @field_validator("rules")
    @classmethod
    def canonicalize_rules(
        cls, values: tuple[PrerequisiteRule, ...]
    ) -> tuple[PrerequisiteRule, ...]:
        if len({rule.tech_id for rule in values}) != len(values):
            raise ValueError("duplicate prerequisite rule")
        return tuple(sorted(values, key=lambda rule: rule.tech_id))


def default_prerequisites() -> PrerequisiteSnapshot:
    """C's explicit learning sequence policy, not an inferred dependency graph.

    Unlisted technologies have no prerequisite imposed by this policy version.
    The policy does not claim that they have no prerequisites in the real world.
    """
    pairs = (
        ("spring-boot", "java"),
        ("spring-data-jpa", "spring-boot"),
        ("spring-actuator", "spring-boot"),
        ("nodejs", "javascript"),
        ("react", "javascript"),
        ("nextjs", "react"),
        ("vuejs", "javascript"),
        ("fastapi", "python"),
    )
    return PrerequisiteSnapshot(
        version=PREREQUISITE_POLICY_VERSION,
        rules=tuple(
            PrerequisiteRule(
                tech_id=tech_id,
                required_tech_ids=(prerequisite,),
                fact_ids=(f"prerequisite:{PREREQUISITE_POLICY_VERSION}:{tech_id}",),
            )
            for tech_id, prerequisite in pairs
        ),
    )


def matches_required_clauses(
    clauses: tuple[tuple[str, ...], ...], held_tech_ids: frozenset[str]
) -> bool:
    """Conjunction of nonempty alternatives; an empty requirement never matches."""
    return bool(clauses) and all(
        bool(clause) and any(tech_id in held_tech_ids for tech_id in clause)
        for clause in clauses
    )


def _matching_job_ids(
    jobs: tuple[CohortJob, ...], held: frozenset[str]
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                job.job_id
                for job in jobs
                if matches_required_clauses(job.required_clauses, held)
            }
        )
    )


class WhatIfResult(EvidenceModel):
    tech_id: TechId
    cohort_id: NonBlank
    held_policy_version: HeldPolicyVersion = HELD_POLICY_VERSION
    denominator: StrictInt = Field(ge=0)
    current_count: StrictInt = Field(ge=0)
    projected_count: StrictInt = Field(ge=0)
    increased_count: StrictInt = Field(ge=0)
    current_job_ids: tuple[NonBlank, ...]
    projected_job_ids: tuple[NonBlank, ...]
    newly_matched_job_ids: tuple[NonBlank, ...]
    data_gaps: tuple[NonBlank, ...] = ()

    @model_validator(mode="after")
    def reconcile_counts_and_lists(self) -> "WhatIfResult":
        for ids in (
            self.current_job_ids,
            self.projected_job_ids,
            self.newly_matched_job_ids,
        ):
            if ids != tuple(sorted(set(ids))):
                raise ValueError("job IDs must be unique and sorted")
        if (
            self.current_count != len(self.current_job_ids)
            or self.projected_count != len(self.projected_job_ids)
            or self.increased_count != len(self.newly_matched_job_ids)
        ):
            raise ValueError("What-if counts must match corresponding job IDs")
        if not set(self.current_job_ids) <= set(self.projected_job_ids):
            raise ValueError("adding one technology cannot remove current jobs")
        if set(self.newly_matched_job_ids) != set(self.projected_job_ids) - set(
            self.current_job_ids
        ):
            raise ValueError("WHAT_IF IDs must be newly matched jobs only")
        if self.projected_count > self.denominator:
            raise ValueError("projected count exceeds cohort denominator")
        return self


def simulate_what_if(
    cohort: JobCohort,
    selection: HeldTechnologySelection,
    tech_id: str,
) -> WhatIfResult:
    """Compare the held set with exactly one evaluated, nonheld technology added."""
    if cohort.criteria.purpose is not CohortPurpose.ACTIVE_MATCHING:
        raise ValueError("ACTIVE_MATCHING_COHORT_REQUIRED")
    if cohort.registry_version != selection.registry_version:
        raise ValueError("Registry versions must match for What-if")
    if tech_id in selection.held_tech_ids:
        raise ValueError("What-if technology is already held")
    decision = selection.by_tech_id.get(tech_id)
    if decision is None or decision.status is HeldStatus.UNKNOWN:
        raise ValueError("What-if technology has unconfirmed Evidence coverage")
    held = frozenset(selection.held_tech_ids)
    current = _matching_job_ids(cohort.jobs, held)
    projected = _matching_job_ids(cohort.jobs, held | {tech_id})
    newly_matched = tuple(sorted(set(projected) - set(current)))
    return WhatIfResult(
        tech_id=tech_id,
        cohort_id=cohort.cohort_id,
        held_policy_version=selection.held_policy_version,
        denominator=len(cohort.jobs),
        current_count=len(current),
        projected_count=len(projected),
        increased_count=len(newly_matched),
        current_job_ids=current,
        projected_job_ids=projected,
        newly_matched_job_ids=newly_matched,
        data_gaps=selection.data_gaps,
    )


class RecommendationCandidate(EvidenceModel):
    tech_id: TechId
    rank: StrictInt = Field(ge=1, le=3)
    demand: TechnologyDemand
    evidence_status: Literal["NOT_HELD"] = "NOT_HELD"
    prerequisite_tech_ids: tuple[TechId, ...]
    missing_prerequisite_tech_ids: tuple[TechId, ...]
    unknown_prerequisite_tech_ids: tuple[TechId, ...]
    reason_codes: tuple[NonBlank, ...]
    fact_ids: tuple[NonBlank, ...]
    what_if: WhatIfResult


class _RecommendationContent(EvidenceModel):
    schema_version: Literal[
        "recommendation-snapshot/v1", "recommendation-snapshot/v2"
    ] = "recommendation-snapshot/v2"
    user_id: NonBlank
    analysis_id: NonBlank
    cohort_id: NonBlank
    status: Literal[
        "READY",
        "PARTIAL",
        "NO_CANDIDATES",
        "INSUFFICIENT_DATA",
        "INSUFFICIENT_EVIDENCE",
    ]
    algorithm_version: Literal[
        "c-recommendation/lexicographic/v1", "c-recommendation/lexicographic/v2"
    ] = RECOMMENDATION_ALGORITHM_VERSION
    prerequisite_policy_version: NonBlank
    prerequisite_snapshot: PrerequisiteSnapshot
    tie_break_rule: Literal[
        "prerequisites-ready,gain-desc,required-count-desc,uncertainty-asc,total-count-desc,tech-id-asc"
    ] = TIE_BREAK_RULE
    demand: DemandSnapshot
    held: Annotated[
        HeldTechnologySelection | LegacyHeldTechnologySelection,
        Field(discriminator="schema_version"),
    ]
    gap: Annotated[
        GapSnapshot | LegacyGapSnapshot, Field(discriminator="schema_version")
    ]
    current_count: StrictInt = Field(ge=0)
    current_job_ids: tuple[NonBlank, ...]
    candidates: tuple[RecommendationCandidate, ...] = Field(max_length=3)
    jobs: tuple[CohortJob, ...]
    data_gaps: tuple[NonBlank, ...]


def _snapshot_id(payload: dict) -> str:
    content = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "recommendation-" + sha256(content.encode("utf-8")).hexdigest()


class RecommendationSnapshot(_RecommendationContent):
    snapshot_id: NonBlank

    @model_validator(mode="after")
    def verify_reproducible_result(self) -> "RecommendationSnapshot":
        if self.demand.criteria.purpose is not CohortPurpose.ACTIVE_MATCHING:
            raise ValueError("ACTIVE_MATCHING_COHORT_REQUIRED")
        if (
            self.user_id != self.held.user_id
            or self.analysis_id != self.held.analysis_id
            or self.gap.user_id != self.user_id
            or self.gap.analysis_id != self.analysis_id
        ):
            raise ValueError("snapshot Evidence/Gap identity mismatch")
        if self.held.held_policy_version != self.gap.held_policy_version:
            raise ValueError("snapshot Evidence/Gap policy mismatch")
        if self.cohort_id != self.demand.cohort_id or self.demand.denominator != len(
            self.jobs
        ):
            raise ValueError("snapshot cohort/demand mismatch")
        expected_current = _matching_job_ids(
            self.jobs, frozenset(self.held.held_tech_ids)
        )
        if self.current_job_ids != expected_current or self.current_count != len(
            expected_current
        ):
            raise ValueError("current count/list must match held-policy matching")
        if tuple(candidate.rank for candidate in self.candidates) != tuple(
            range(1, len(self.candidates) + 1)
        ):
            raise ValueError("candidate ranks must be contiguous")
        if len({candidate.tech_id for candidate in self.candidates}) != len(
            self.candidates
        ):
            raise ValueError("duplicate recommendation candidate")
        for candidate in self.candidates:
            if candidate.tech_id not in self.gap.missing_tech_ids:
                raise ValueError("candidate must be an evaluated missing technology")
            projected = _matching_job_ids(
                self.jobs, frozenset(self.held.held_tech_ids) | {candidate.tech_id}
            )
            if (
                candidate.what_if.current_job_ids != expected_current
                or candidate.what_if.projected_job_ids != projected
                or candidate.what_if.cohort_id != self.cohort_id
                or candidate.what_if.tech_id != candidate.tech_id
                or candidate.what_if.held_policy_version
                != self.held.held_policy_version
            ):
                raise ValueError(
                    "candidate What-if must use the snapshot cohort and held set"
                )
        if self.snapshot_id != _snapshot_id(
            self.model_dump(mode="json", exclude={"snapshot_id"})
        ):
            raise ValueError("snapshot content does not match immutable snapshot_id")
        return self


def build_recommendations(
    cohort: JobCohort,
    analysis: EvidenceAnalysis,
    *,
    user_id: str,
    analysis_id: str,
    prerequisites: PrerequisiteSnapshot | None = None,
) -> RecommendationSnapshot:
    """Rank at most three missing technologies; all counts share one cohort.

    UNKNOWN is excluded from the missing-candidate pool. Trend is served as
    separate source-specific observations and has no hidden ranking weight.
    """
    if cohort.criteria.purpose is not CohortPurpose.ACTIVE_MATCHING:
        raise ValueError("ACTIVE_MATCHING_COHORT_REQUIRED")
    if cohort.registry_version != analysis.registry_version:
        raise ValueError("Registry versions must match for recommendation")
    prerequisites = prerequisites or default_prerequisites()
    demand = aggregate_demand(cohort)
    demand_ids = {row.tech_id for row in demand.technologies}
    prerequisite_rules = {rule.tech_id: rule for rule in prerequisites.rules}
    relevant_prerequisites = {
        tech_id
        for rule in prerequisites.rules
        if rule.tech_id in demand_ids
        for tech_id in rule.required_tech_ids
    }
    held = consume_evidence(
        analysis,
        user_id=user_id,
        analysis_id=analysis_id,
        tech_ids=demand_ids | relevant_prerequisites,
    )
    gap = build_gap(held, demanded_tech_ids=demand_ids)
    decisions = held.by_tech_id
    current_ids = _matching_job_ids(cohort.jobs, frozenset(held.held_tech_ids))
    data_gaps = set(gap.data_gaps)
    if cohort.review_count:
        data_gaps.add(f"COHORT_RECORDS_REQUIRE_REVIEW:{cohort.review_count}")
    if cohort.status is not CohortStatus.READY:
        data_gaps.add(f"COHORT_{cohort.status.value}")

    ranked: list[tuple[tuple, dict]] = []
    for row in demand.technologies:
        if (
            cohort.status is not CohortStatus.READY
            or row.tech_id not in gap.missing_tech_ids
        ):
            continue
        rule = prerequisite_rules.get(row.tech_id)
        required = rule.required_tech_ids if rule else ()
        missing = tuple(
            tech_id
            for tech_id in required
            if decisions[tech_id].status is HeldStatus.NOT_HELD
        )
        unknown = tuple(
            tech_id
            for tech_id in required
            if decisions[tech_id].status is HeldStatus.UNKNOWN
        )
        what_if = simulate_what_if(cohort, held, row.tech_id)
        reasons = {
            "DEMAND_IN_SELECTED_COHORT",
            "NO_HELD_EVIDENCE_UNDER_SELECTED_POLICY",
        }
        reasons.add(
            "DIRECT_JOB_INCREASE"
            if what_if.increased_count
            else "NO_IMMEDIATE_JOB_INCREASE"
        )
        if missing:
            reasons.add("PREREQUISITES_MISSING")
        if unknown:
            reasons.add("PREREQUISITE_EVIDENCE_UNCONFIRMED")
        if required and not missing and not unknown:
            reasons.add("PREREQUISITES_HELD")
        if not required:
            reasons.add("NO_PREREQUISITE_IMPOSED_BY_POLICY")
        fact_ids = {
            f"demand:{cohort.cohort_id}:{row.tech_id}",
            f"evidence:{analysis.analysis_id}:{row.tech_id}",
            f"what-if:{cohort.cohort_id}:{row.tech_id}",
            *(
                f"job:{cohort.cohort_id}:{job_id}"
                for job_id in what_if.newly_matched_job_ids
            ),
        }
        if rule:
            fact_ids.update(rule.fact_ids)
        uncertainty = len(unknown) + len(decisions[row.tech_id].data_gaps)
        key = (
            bool(missing or unknown),
            -what_if.increased_count,
            -row.required_count,
            uncertainty,
            -row.total_count,
            row.tech_id,
        )
        ranked.append(
            (
                key,
                {
                    "tech_id": row.tech_id,
                    "demand": row,
                    "prerequisite_tech_ids": required,
                    "missing_prerequisite_tech_ids": missing,
                    "unknown_prerequisite_tech_ids": unknown,
                    "reason_codes": tuple(sorted(reasons)),
                    "fact_ids": tuple(sorted(fact_ids)),
                    "what_if": what_if,
                },
            )
        )
    candidates = tuple(
        RecommendationCandidate(rank=rank, **payload)
        for rank, (_, payload) in enumerate(
            sorted(ranked, key=lambda item: item[0])[:3], start=1
        )
    )
    if cohort.status is not CohortStatus.READY:
        status = "INSUFFICIENT_DATA"
    elif not candidates and gap.unknown_tech_ids:
        status = "INSUFFICIENT_EVIDENCE"
    elif not candidates:
        status = "NO_CANDIDATES"
    else:
        status = "PARTIAL" if data_gaps else "READY"
    content = _RecommendationContent(
        user_id=user_id,
        analysis_id=analysis_id,
        cohort_id=cohort.cohort_id,
        status=status,
        prerequisite_policy_version=prerequisites.version,
        prerequisite_snapshot=prerequisites,
        demand=demand,
        held=held,
        gap=gap,
        current_count=len(current_ids),
        current_job_ids=current_ids,
        candidates=candidates,
        jobs=tuple(sorted(cohort.jobs, key=lambda job: job.job_id)),
        data_gaps=tuple(sorted(data_gaps)),
    ).model_dump(mode="json")
    return RecommendationSnapshot(snapshot_id=_snapshot_id(content), **content)


class RelatedJobsPage(EvidenceModel):
    snapshot_id: NonBlank
    cohort_id: NonBlank
    view: Literal["CURRENT", "WHAT_IF"]
    tech_id: TechId | None
    total_count: StrictInt = Field(ge=0)
    offset: StrictInt = Field(ge=0)
    limit: StrictInt = Field(ge=1, le=100)
    current_count: StrictInt = Field(ge=0)
    projected_count: StrictInt = Field(ge=0)
    increased_count: StrictInt = Field(ge=0)
    items: tuple[CohortJob, ...]
    data_gaps: tuple[NonBlank, ...]


def list_related_jobs(
    snapshot: RecommendationSnapshot,
    *,
    user_id: str,
    view: Literal["CURRENT", "WHAT_IF"],
    tech_id: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> RelatedJobsPage:
    """Read immutable CURRENT IDs or WHAT_IF newly-added IDs, without recompute."""
    if snapshot.user_id != user_id:
        raise PermissionError("recommendation snapshot belongs to another user")
    if (
        type(offset) is not int
        or type(limit) is not int
        or offset < 0
        or not 1 <= limit <= 100
    ):
        raise ValueError("offset must be nonnegative and limit must be in 1..100")
    if view == "CURRENT":
        if tech_id is not None:
            raise ValueError("CURRENT list does not take a candidate technology")
        ids, projected_count, increased_count = (
            snapshot.current_job_ids,
            snapshot.current_count,
            0,
        )
    elif view == "WHAT_IF":
        candidate = next(
            (item for item in snapshot.candidates if item.tech_id == tech_id), None
        )
        if candidate is None:
            raise ValueError("WHAT_IF list requires a candidate in this snapshot")
        ids = candidate.what_if.newly_matched_job_ids
        projected_count, increased_count = (
            candidate.what_if.projected_count,
            candidate.what_if.increased_count,
        )
    else:
        raise ValueError("view must be CURRENT or WHAT_IF")
    jobs = {job.job_id: job for job in snapshot.jobs}
    return RelatedJobsPage(
        snapshot_id=snapshot.snapshot_id,
        cohort_id=snapshot.cohort_id,
        view=view,
        tech_id=tech_id,
        total_count=len(ids),
        offset=offset,
        limit=limit,
        current_count=snapshot.current_count,
        projected_count=projected_count,
        increased_count=increased_count,
        items=tuple(jobs[job_id] for job_id in ids[offset : offset + limit]),
        data_gaps=snapshot.data_gaps,
    )
