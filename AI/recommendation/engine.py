"""Deterministic next-technology candidates and one-technology job deltas."""

import json
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import Field, StrictInt, field_validator, model_validator

from job.cohort import CohortJob, CohortPurpose, CohortStatus, JobCohort
from job.demand import DemandSnapshot, TechnologyDemand, aggregate_demand
from job.matching import MatchingJobInput
from job.requirements import RequirementKind
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
    consume_personal_assessments,
    consume_personal_levels,
)
from registry.contracts import TechId

#: S15P21E102-354 changed who may be a candidate, so it is a new calculation and
#: not a new reading of the old one. v6 stays for reading stored results.
NEW_SKILL_ALGORITHM_VERSION = "c-recommendation/lexicographic/v7"
RECOMMENDATION_ALGORITHM_VERSION = NEW_SKILL_ALGORITHM_VERSION
EXPANDED_ALGORITHM_VERSIONS = frozenset(
    {"c-recommendation/lexicographic/v6", NEW_SKILL_ALGORITHM_VERSION}
)
PREREQUISITE_POLICY_VERSION = "c-learning-prerequisites/v1"
LEGACY_TIE_BREAK_RULE = "prerequisites-ready,gain-desc,required-count-desc,uncertainty-asc,total-count-desc,tech-id-asc"
TIE_BREAK_RULE = "gain-desc,prerequisites-ready,required-count-desc,uncertainty-asc,total-count-desc,tech-id-asc"


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


RecommendationJob = CohortJob | MatchingJobInput


def _required_clauses(job: RecommendationJob) -> tuple[tuple[str, ...], ...]:
    if isinstance(job, MatchingJobInput):
        return tuple(clause.tech_ids for clause in job.requirements.required)
    return job.required_clauses


def _levelled_required_clauses(job: RecommendationJob):
    if isinstance(job, MatchingJobInput):
        clauses = job.requirements.required
        return (
            clauses
            if all(clause.required_level is not None for clause in clauses)
            else None
        )
    return job.levelled_required_clauses


def _has_unresolved_required(job: RecommendationJob) -> bool:
    return isinstance(job, MatchingJobInput) and any(
        item.requirement_kind is RequirementKind.REQUIRED
        for item in job.requirements.unresolved
    )


def _is_eligible(job: RecommendationJob) -> bool:
    return not isinstance(job, MatchingJobInput) or job.eligibility == "ELIGIBLE"


def _matching_job_ids(
    jobs: tuple[RecommendationJob, ...], held: frozenset[str]
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                job.job_id
                for job in jobs
                if _is_eligible(job)
                and not _has_unresolved_required(job)
                and matches_required_clauses(_required_clauses(job), held)
            }
        )
    )


def _level_matching_job_ids(
    jobs: tuple[RecommendationJob, ...], personal_levels: dict[str, str]
) -> tuple[str, ...]:
    """Required clauses only; PREFERRED is deliberately not an eligibility gate."""
    rank = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
    return tuple(
        sorted(
            job.job_id
            for job in jobs
            if _is_eligible(job)
            and not _has_unresolved_required(job)
            and _levelled_required_clauses(job)
            and all(
                any(
                    rank.get(personal_levels.get(tech), -1)
                    >= rank[clause.required_level.value]
                    for tech in clause.tech_ids
                )
                for clause in _levelled_required_clauses(job) or ()
            )
        )
    )


def _unlevelled_required_job_ids(
    jobs: tuple[RecommendationJob, ...],
) -> tuple[str, ...]:
    """Jobs with only legacy clauses cannot be promoted by v3 held evidence."""
    return tuple(
        sorted(
            job.job_id
            for job in jobs
            if _required_clauses(job)
            and (
                _levelled_required_clauses(job) is None or _has_unresolved_required(job)
            )
        )
    )


def _is_candidate_eligible(
    tech_id: str,
    *,
    new_skill_policy: bool,
    level_aware: bool,
    missing_tech_ids,
    personal_levels: dict[str, str],
) -> bool:
    """Whether a demanded technology may be recommended (S15P21E102-354).

    The builder and the snapshot validator must answer this identically -- the
    validator re-checks every stored candidate, so two copies of the rule would
    make freshly built snapshots fail their own round-trip.

    Under the next-skill policy the question is only "has the user personally
    used this yet". A personal level of L1 or above means yes, so it is never a
    candidate -- not even when the posting requires a higher level, because
    levelling up a held technology is a different product decision. L0, no
    personal assessment, and Evidence UNKNOWN all mean "not used yet".

    Older calculations keep the missing-only rule so their stored snapshots stay
    valid; UNKNOWN was never a missing candidate there.
    """
    if new_skill_policy and level_aware:
        return personal_levels.get(tech_id) in (None, "L0")
    return tech_id in missing_tech_ids or (
        level_aware and personal_levels.get(tech_id) == "L0"
    )


def _explicit_personal_assessments(
    analysis: EvidenceAnalysis, held, relevant_tech_ids: set[str]
):
    if analysis.schema_version == "evidence-consumption-input/v4":
        assessments = {
            key: item
            for key, item in consume_personal_assessments(analysis, held).items()
            if key in relevant_tech_ids
        }
        return (
            {key: item.personal_level for key, item in assessments.items()},
            {key: item.assessment_ceiling for key, item in assessments.items()},
            tuple(
                sorted(key for key, item in assessments.items() if item.scope_complete)
            ),
        )
    return consume_personal_levels(analysis, held), {}, ()


def _level_what_if(
    cohort: JobCohort,
    tech_id: str,
    levels: dict[str, str],
    held,
    *,
    data_gaps: tuple[str, ...],
    jobs: tuple[RecommendationJob, ...] | None = None,
):
    calculation_jobs = cohort.jobs if jobs is None else jobs
    current = _level_matching_job_ids(calculation_jobs, levels)
    projected = _level_matching_job_ids(calculation_jobs, {**levels, tech_id: "L1"})
    newly = tuple(sorted(set(projected) - set(current)))
    return WhatIfResult(
        tech_id=tech_id,
        cohort_id=cohort.cohort_id,
        held_policy_version=held.held_policy_version,
        denominator=len(calculation_jobs),
        current_count=len(current),
        projected_count=len(projected),
        increased_count=len(newly),
        current_job_ids=current,
        projected_job_ids=projected,
        newly_matched_job_ids=newly,
        data_gaps=data_gaps,
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
    *,
    jobs: tuple[RecommendationJob, ...] | None = None,
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
    calculation_jobs = cohort.jobs if jobs is None else jobs
    current = _matching_job_ids(calculation_jobs, held)
    projected = _matching_job_ids(calculation_jobs, held | {tech_id})
    newly_matched = tuple(sorted(set(projected) - set(current)))
    return WhatIfResult(
        tech_id=tech_id,
        cohort_id=cohort.cohort_id,
        held_policy_version=selection.held_policy_version,
        denominator=len(calculation_jobs),
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
    #: ``PERSONAL_LEVEL_UNKNOWN`` is the S15P21E102-354 case: the technology is
    #: observed or unevaluated in the repositories but carries no personal level,
    #: so it is offered as a new skill without claiming the user does not hold it.
    evidence_status: Literal["NOT_HELD", "L0", "PERSONAL_LEVEL_UNKNOWN"] = "NOT_HELD"
    prerequisite_tech_ids: tuple[TechId, ...]
    missing_prerequisite_tech_ids: tuple[TechId, ...]
    unknown_prerequisite_tech_ids: tuple[TechId, ...]
    reason_codes: tuple[NonBlank, ...]
    fact_ids: tuple[NonBlank, ...]
    what_if: WhatIfResult


class _RecommendationContent(EvidenceModel):
    schema_version: Literal[
        "recommendation-snapshot/v1",
        "recommendation-snapshot/v2",
        "recommendation-snapshot/v3",
    ] = "recommendation-snapshot/v2"
    evidence_input_version: (
        Literal[
            "evidence-consumption-input/v1",
            "evidence-consumption-input/v2",
            "evidence-consumption-input/v3",
            "evidence-consumption-input/v4",
        ]
        | None
    ) = Field(default=None, exclude_if=lambda value: value is None)
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
        "c-recommendation/lexicographic/v1",
        "c-recommendation/lexicographic/v2",
        "c-recommendation/lexicographic/v3",
        "c-recommendation/lexicographic/v4",
        "c-recommendation/lexicographic/v5",
        "c-recommendation/lexicographic/v6",
        "c-recommendation/lexicographic/v7",
    ] = RECOMMENDATION_ALGORITHM_VERSION
    prerequisite_policy_version: NonBlank
    prerequisite_snapshot: PrerequisiteSnapshot
    tie_break_rule: Literal[
        "prerequisites-ready,gain-desc,required-count-desc,uncertainty-asc,total-count-desc,tech-id-asc",
        "gain-desc,prerequisites-ready,required-count-desc,uncertainty-asc,total-count-desc,tech-id-asc",
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
    matching_jobs: tuple[MatchingJobInput, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    data_gaps: tuple[NonBlank, ...]
    personal_levels: dict[TechId, Literal["L0", "L1", "L2", "L3"]] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )
    assessment_ceilings: dict[TechId, Literal["L0", "L1", "L2", "L3"]] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )
    level_assessment_complete_tech_ids: tuple[TechId, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )


def _snapshot_id(payload: dict) -> str:
    content = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "recommendation-" + sha256(content.encode("utf-8")).hexdigest()


class RecommendationSnapshot(_RecommendationContent):
    snapshot_id: NonBlank

    @model_validator(mode="after")
    def verify_reproducible_result(self) -> "RecommendationSnapshot":
        expected_rule = (
            TIE_BREAK_RULE
            if self.algorithm_version
            in {
                "c-recommendation/lexicographic/v3",
                "c-recommendation/lexicographic/v4",
                "c-recommendation/lexicographic/v5",
                "c-recommendation/lexicographic/v6",
                NEW_SKILL_ALGORITHM_VERSION,
            }
            else LEGACY_TIE_BREAK_RULE
        )
        if self.tie_break_rule != expected_rule:
            raise ValueError("recommendation formula and rank policy mismatch")
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
        expanded = self.algorithm_version in EXPANDED_ALGORITHM_VERSIONS
        if expanded and (
            self.schema_version != "recommendation-snapshot/v3"
            or self.evidence_input_version is None
            or self.matching_jobs is None
        ):
            raise ValueError("v6 recommendation requires expanded matching inputs")
        if not expanded and self.matching_jobs is not None:
            raise ValueError("expanded matching inputs require recommendation v6")
        calculation_jobs: tuple[RecommendationJob, ...] = (
            self.matching_jobs
            if expanded and self.matching_jobs is not None
            else self.jobs
        )
        if self.cohort_id != self.demand.cohort_id or self.demand.denominator != len(
            calculation_jobs
        ):
            raise ValueError("snapshot cohort/demand mismatch")
        level_aware = (
            self.evidence_input_version
            in {"evidence-consumption-input/v3", "evidence-consumption-input/v4"}
            if expanded
            else self.algorithm_version
            in {
                "c-recommendation/lexicographic/v4",
                "c-recommendation/lexicographic/v5",
            }
        )
        expected_current = (
            _level_matching_job_ids(calculation_jobs, self.personal_levels)
            if level_aware
            else _matching_job_ids(calculation_jobs, frozenset(self.held.held_tech_ids))
        )
        ceiling_aware = (
            self.algorithm_version == "c-recommendation/lexicographic/v5"
            or (
                expanded
                and self.evidence_input_version == "evidence-consumption-input/v4"
            )
        )
        if ceiling_aware:
            if set(self.assessment_ceilings) != set(self.personal_levels):
                raise ValueError("v5 personal levels require assessment ceilings")
            if not set(self.level_assessment_complete_tech_ids) <= set(
                self.personal_levels
            ):
                raise ValueError("complete level assessment has no personal level")
            if self.level_assessment_complete_tech_ids != tuple(
                sorted(set(self.level_assessment_complete_tech_ids))
            ):
                raise ValueError(
                    "complete level assessment IDs must be unique and sorted"
                )
            rank = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
            if any(
                rank[level] > rank[self.assessment_ceilings[tech]]
                for tech, level in self.personal_levels.items()
            ):
                raise ValueError("personal level is above assessment ceiling")
        elif self.assessment_ceilings or self.level_assessment_complete_tech_ids:
            raise ValueError("assessment ceiling metadata requires v5")
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
        new_skill_policy = self.algorithm_version == NEW_SKILL_ALGORITHM_VERSION
        for candidate in self.candidates:
            if not _is_candidate_eligible(
                candidate.tech_id,
                new_skill_policy=new_skill_policy,
                level_aware=level_aware,
                missing_tech_ids=self.gap.missing_tech_ids,
                personal_levels=self.personal_levels,
            ):
                raise ValueError("candidate must be an evaluated missing technology")
            projected = (
                _level_matching_job_ids(
                    calculation_jobs,
                    {**self.personal_levels, candidate.tech_id: "L1"},
                )
                if level_aware
                else _matching_job_ids(
                    calculation_jobs,
                    frozenset(self.held.held_tech_ids) | {candidate.tech_id},
                )
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
    expanded = cohort.matching_jobs is not None
    calculation_jobs: tuple[RecommendationJob, ...] = (
        cohort.matching_jobs if cohort.matching_jobs is not None else cohort.jobs
    )
    calculation_status = CohortStatus.for_size(
        len(calculation_jobs), cohort.criteria.min_jobs
    )
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
    (
        personal_levels,
        assessment_ceilings,
        level_assessment_complete_tech_ids,
    ) = _explicit_personal_assessments(
        analysis, held, demand_ids | relevant_prerequisites
    )
    level_aware = analysis.schema_version in {
        "evidence-consumption-input/v3",
        "evidence-consumption-input/v4",
    }
    current_ids = (
        _level_matching_job_ids(calculation_jobs, personal_levels)
        if level_aware
        else _matching_job_ids(calculation_jobs, frozenset(held.held_tech_ids))
    )
    data_gaps = set(gap.data_gaps)
    unlevelled_required_job_ids = (
        _unlevelled_required_job_ids(calculation_jobs) if level_aware else ()
    )
    data_gaps.update(
        f"REQUIRED_LEVEL_UNCONFIRMED:{job_id}" for job_id in unlevelled_required_job_ids
    )
    personal_level_unconfirmed = tuple(
        sorted(
            tech_id
            for tech_id in demand_ids
            if level_aware
            and decisions[tech_id].status is HeldStatus.HELD
            and tech_id not in personal_levels
        )
    )
    data_gaps.update(
        f"PERSONAL_LEVEL_UNCONFIRMED:{tech_id}"
        for tech_id in personal_level_unconfirmed
    )
    if analysis.schema_version == "evidence-consumption-input/v4":
        complete_level_ids = set(level_assessment_complete_tech_ids)
        rank = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
        for job in calculation_jobs:
            for clause in _levelled_required_clauses(job) or ():
                required = clause.required_level.value
                if any(
                    rank.get(personal_levels.get(tech), -1) >= rank[required]
                    for tech in clause.tech_ids
                ):
                    continue
                for tech in clause.tech_ids:
                    if decisions[tech].status is not HeldStatus.HELD:
                        continue
                    if tech not in assessment_ceilings:
                        data_gaps.add(f"PERSONAL_LEVEL_ASSESSMENT_UNCONFIRMED:{tech}")
                    elif rank[assessment_ceilings[tech]] < rank[required]:
                        data_gaps.add(
                            f"ASSESSMENT_CEILING_BELOW_REQUIREMENT:{tech}:{required}"
                        )
                    elif tech not in complete_level_ids:
                        data_gaps.add(f"PERSONAL_LEVEL_SCOPE_INCOMPLETE:{tech}")
    if cohort.review_count:
        data_gaps.add(f"COHORT_RECORDS_REQUIRE_REVIEW:{cohort.review_count}")
    if calculation_status is not CohortStatus.READY:
        data_gaps.add(f"COHORT_{calculation_status.value}")

    algorithm_version = (
        NEW_SKILL_ALGORITHM_VERSION
        if expanded
        else "c-recommendation/lexicographic/v5"
        if analysis.schema_version == "evidence-consumption-input/v4" and level_aware
        else "c-recommendation/lexicographic/v4"
        if level_aware
        else "c-recommendation/lexicographic/v3"
    )
    # Derived from the version actually emitted, so the builder and the snapshot
    # validator cannot drift apart on who is eligible.
    new_skill_policy = algorithm_version == NEW_SKILL_ALGORITHM_VERSION

    ranked: list[tuple[tuple, dict]] = []
    for row in demand.technologies:
        if calculation_status is not CohortStatus.READY or not _is_candidate_eligible(
            row.tech_id,
            new_skill_policy=new_skill_policy,
            level_aware=level_aware,
            missing_tech_ids=gap.missing_tech_ids,
            personal_levels=personal_levels,
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
        what_if = (
            _level_what_if(
                cohort,
                row.tech_id,
                personal_levels,
                held,
                data_gaps=tuple(sorted(data_gaps)),
                jobs=calculation_jobs,
            )
            if level_aware
            else simulate_what_if(cohort, held, row.tech_id, jobs=calculation_jobs)
        )
        held_l0 = level_aware and personal_levels.get(row.tech_id) == "L0"
        reasons = {"DEMAND_IN_SELECTED_COHORT"}
        # A technology the user demonstrably holds must not be explained as "no
        # held evidence". S15P21E102-354 recommends it for the absence of
        # *personal* use, which is a different claim.
        reasons.add(
            "NO_HELD_EVIDENCE_UNDER_SELECTED_POLICY"
            if row.tech_id in gap.missing_tech_ids or held_l0
            else "NO_PERSONAL_USE_EVIDENCE"
        )
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
            -what_if.increased_count,
            bool(missing or unknown),
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
                    "evidence_status": (
                        "L0"
                        if held_l0
                        else "NOT_HELD"
                        if row.tech_id in gap.missing_tech_ids
                        else "PERSONAL_LEVEL_UNKNOWN"
                    ),
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
    if calculation_status is not CohortStatus.READY:
        status = "INSUFFICIENT_DATA"
    elif not candidates and (
        gap.unknown_tech_ids
        or personal_level_unconfirmed
        or unlevelled_required_job_ids
    ):
        status = "INSUFFICIENT_EVIDENCE"
    elif not candidates:
        status = "NO_CANDIDATES"
    else:
        status = "PARTIAL" if data_gaps else "READY"
    content = _RecommendationContent(
        schema_version=(
            "recommendation-snapshot/v3" if expanded else "recommendation-snapshot/v2"
        ),
        evidence_input_version=(analysis.schema_version if expanded else None),
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
        matching_jobs=(
            tuple(sorted(cohort.matching_jobs, key=lambda job: job.job_id))
            if cohort.matching_jobs is not None
            else None
        ),
        data_gaps=tuple(sorted(data_gaps)),
        algorithm_version=algorithm_version,
        personal_levels=personal_levels if level_aware else {},
        assessment_ceilings=assessment_ceilings if level_aware else {},
        level_assessment_complete_tech_ids=(
            level_assessment_complete_tech_ids if level_aware else ()
        ),
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
    items: tuple[CohortJob | MatchingJobInput, ...]
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
    source_jobs: tuple[RecommendationJob, ...] = (
        snapshot.matching_jobs
        if snapshot.algorithm_version in EXPANDED_ALGORITHM_VERSIONS
        and snapshot.matching_jobs is not None
        else snapshot.jobs
    )
    jobs = {job.job_id: job for job in source_jobs}
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
