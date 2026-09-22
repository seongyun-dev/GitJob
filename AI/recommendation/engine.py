"""Deterministic next-technology candidates and related-job counts."""

import json
from collections.abc import Callable, Mapping
from collections.abc import Set as AbstractSet
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
from recommendation.trend_tiebreak import TieBreakCandidate, apply_trend_tiebreak
from registry.contracts import TechId

#: S15P21E102-354 changed who may be a candidate, so it is a new calculation and
#: not a new reading of the old one. v6 stays for reading stored results.
NEW_SKILL_ALGORITHM_VERSION = "c-recommendation/condition-impact/v8"
RECOMMENDATION_ALGORITHM_VERSION = NEW_SKILL_ALGORITHM_VERSION
EXPANDED_ALGORITHM_VERSIONS = frozenset(
    {
        "c-recommendation/lexicographic/v6",
        "c-recommendation/lexicographic/v7",
        NEW_SKILL_ALGORITHM_VERSION,
    }
)
PREREQUISITE_POLICY_VERSION = "c-learning-prerequisites/v1"
LEGACY_TIE_BREAK_RULE = "prerequisites-ready,gain-desc,required-count-desc,uncertainty-asc,total-count-desc,tech-id-asc"
TIE_BREAK_RULE = "gain-desc,prerequisites-ready,required-count-desc,uncertainty-asc,total-count-desc,tech-id-asc"
#: S15P21E102-355. 순서 규칙만 다르고 계산은 같으므로 `algorithm_version` 이 아니라
#: 여기서 갈린다 -- 후보 자격도, `increased_count` 도, What-if 도 v7 그대로다.
#: 이름에 `top3` 가 들어가는 것은 이 규칙이 **Top3 를 고른 뒤에만** 도는 것이
#: 규칙의 일부이기 때문이다. 4위 후보는 이 비교에 참여하지 않는다.
TREND_TIE_BREAK_RULE = (
    "gain-desc,top3-near-tie-weekly-active-repo-v1,prerequisites-ready,"
    "required-count-desc,uncertainty-asc,total-count-desc,tech-id-asc"
)
IMPACT_TIE_BREAK_RULE = (
    "affected-jobs-desc,required-jobs-desc,prerequisites-ready,"
    "required-demand-desc,uncertainty-asc,total-demand-desc,tech-id-asc"
)
IMPACT_TREND_TIE_BREAK_RULE = (
    "affected-jobs-desc,top3-near-tie-weekly-active-repo-v1,"
    "required-jobs-desc,prerequisites-ready,required-demand-desc,"
    "uncertainty-asc,total-demand-desc,tech-id-asc"
)


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


class ConditionImpact(EvidenceModel):
    """Postings that explicitly mention one candidate in resolved requirements.

    This is not a full-job or personal-level match. Each list counts distinct
    postings, not clauses; a posting can mention the technology in both kinds.
    """

    tech_id: TechId
    cohort_id: NonBlank
    denominator: StrictInt = Field(ge=0)
    required_job_ids: tuple[NonBlank, ...]
    preferred_job_ids: tuple[NonBlank, ...]
    affected_job_ids: tuple[NonBlank, ...]
    required_count: StrictInt = Field(ge=0)
    preferred_count: StrictInt = Field(ge=0)
    affected_count: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def verify_counts(self) -> "ConditionImpact":
        for ids in (
            self.required_job_ids,
            self.preferred_job_ids,
            self.affected_job_ids,
        ):
            if ids != tuple(sorted(set(ids))):
                raise ValueError("impact job IDs must be unique and sorted")
        if self.affected_job_ids != tuple(
            sorted(set(self.required_job_ids) | set(self.preferred_job_ids))
        ):
            raise ValueError("affected jobs must be the required/preferred union")
        if (
            self.required_count != len(self.required_job_ids)
            or self.preferred_count != len(self.preferred_job_ids)
            or self.affected_count != len(self.affected_job_ids)
            or self.affected_count > self.denominator
        ):
            raise ValueError("impact counts must match posting IDs and denominator")
        return self


def condition_impact(
    jobs: tuple[MatchingJobInput, ...],
    _held_tech_ids: frozenset[str],
    _personal_levels: dict[str, str],
    tech_id: str,
    cohort_id: str,
) -> ConditionImpact:
    """Count candidate mentions in parsed clauses, independent of current level.

    Learning at L1 does not establish eligibility for an L2/L3 requirement, so
    these counts describe relevant openings rather than newly fulfilled jobs.
    Unresolved/general mentions are not promoted to required or preferred.
    """
    required_ids: set[str] = set()
    preferred_ids: set[str] = set()
    for job in jobs:
        for clause in job.requirements.required:
            if tech_id in clause.tech_ids:
                required_ids.add(job.job_id)
        for clause in job.requirements.preferred:
            if tech_id in clause.tech_ids:
                preferred_ids.add(job.job_id)
    required = tuple(sorted(required_ids))
    preferred = tuple(sorted(preferred_ids))
    affected = tuple(sorted(required_ids | preferred_ids))
    return ConditionImpact(
        tech_id=tech_id,
        cohort_id=cohort_id,
        denominator=len(jobs),
        required_job_ids=required,
        preferred_job_ids=preferred,
        affected_job_ids=affected,
        required_count=len(required),
        preferred_count=len(preferred),
        affected_count=len(affected),
    )


def active_condition_impact(
    impact: ConditionImpact, active_job_ids: AbstractSet[str] | None
) -> ConditionImpact:
    """Apply the same live-availability gate to card counts and detail lists."""
    if active_job_ids is None:
        return impact
    required = tuple(job for job in impact.required_job_ids if job in active_job_ids)
    preferred = tuple(job for job in impact.preferred_job_ids if job in active_job_ids)
    affected = tuple(sorted(set(required) | set(preferred)))
    return ConditionImpact(
        tech_id=impact.tech_id,
        cohort_id=impact.cohort_id,
        denominator=impact.denominator,
        required_job_ids=required,
        preferred_job_ids=preferred,
        affected_job_ids=affected,
        required_count=len(required),
        preferred_count=len(preferred),
        affected_count=len(affected),
    )


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


class TrendTieBreakBasis(EvidenceModel):
    """어떤 주차의 어떤 값으로 Top3 순서를 갈랐는지 (S15P21E102-355).

    <h2>왜 값을 결과에 남기는가</h2>

    Trend head 는 주마다 새로 쌓인다. 근거를 남기지 않으면 저장된 순서를 나중에
    재현할 수 없고, "왜 Redis 가 Docker 앞인가"에 답할 수 없다. 기간·출처·지표와
    후보별 값을 함께 고정하면 저장된 결과만으로 정렬을 다시 계산해 검증할 수 있다.

    <h2>왜 없는 값을 0으로 적지 않는가</h2>

    `values` 에는 **실제로 관측된 기술만** 들어간다. 측정하지 않은 것을 0으로
    적으면 그 기술이 그 주에 한 저장소도 안 쓰였다는 거짓 사실이 저장되고, 다시
    읽는 쪽은 그것을 진짜 0으로 읽는다. 빠진 것은 빠진 채로 둔다.
    """

    source: Literal["GITHUB_GH_ARCHIVE"]
    granularity: Literal["WEEK"]
    period: NonBlank
    #: 순위에 쓴 point 필드. 같은 point 의 `event_count` 는 기술마다 중복
    #: 합산이라 순위로 쓸 수 없으므로 이 Literal 에 들어가지 않는다.
    metric: Literal["active_repo_count"]
    values: dict[TechId, StrictInt]

    @model_validator(mode="after")
    def verify_bounded_and_observed(self) -> "TrendTieBreakBasis":
        if not self.values:
            raise ValueError("trend tie-break basis must carry an observed value")
        if len(self.values) > 3:
            raise ValueError("trend tie-break basis is bounded to the Top3")
        if any(value < 0 for value in self.values.values()):
            raise ValueError("active_repo_count must not be negative")
        return self


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
    what_if: WhatIfResult | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    impact: ConditionImpact | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class _RecommendationContent(EvidenceModel):
    schema_version: Literal[
        "recommendation-snapshot/v1",
        "recommendation-snapshot/v2",
        "recommendation-snapshot/v3",
        "recommendation-snapshot/v4",
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
        "c-recommendation/condition-impact/v8",
    ] = RECOMMENDATION_ALGORITHM_VERSION
    prerequisite_policy_version: NonBlank
    prerequisite_snapshot: PrerequisiteSnapshot
    tie_break_rule: Literal[
        "prerequisites-ready,gain-desc,required-count-desc,uncertainty-asc,total-count-desc,tech-id-asc",
        "gain-desc,prerequisites-ready,required-count-desc,uncertainty-asc,total-count-desc,tech-id-asc",
        (
            "gain-desc,top3-near-tie-weekly-active-repo-v1,prerequisites-ready,"
            "required-count-desc,uncertainty-asc,total-count-desc,tech-id-asc"
        ),
        IMPACT_TIE_BREAK_RULE,
        IMPACT_TREND_TIE_BREAK_RULE,
    ] = TIE_BREAK_RULE
    #: 순서를 바꾼 근거. 값만 남기면 같은 입력이 다른 순서를 낸 이유를 나중에
    #: 설명할 수 없으므로 주차·출처·지표까지 함께 고정한다. 없을 때는 아예
    #: 직렬화하지 않아 기존 payload 바이트가 그대로 유지된다.
    trend_tiebreak: TrendTieBreakBasis | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
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

    @property
    def calculation_jobs(self) -> tuple["RecommendationJob", ...]:
        """The job set every count in this snapshot was computed over.

        확장 계산은 `matching_jobs` 로 CURRENT·What-if 를 세고, 그 이전 계산은
        `jobs` 로 센다. 그러니 저장된 ID 를 공고로 되돌리는 쪽도 **같은 집합** 을
        봐야 한다. 이것이 따로 적혀 있으면 갈라진다 -- 실제로 갈라졌다
        (S15P21E102-361): 설명 계층만 `jobs` 를 보다가 `matching_jobs` 에만 있는
        공고에서 KeyError 로 죽었고, 그 사용자는 추천을 통째로 못 받았다.
        운영 실측은 `jobs` 25건 대 `matching_jobs` 556건이었다.
        """
        return (
            self.matching_jobs
            if self.algorithm_version in EXPANDED_ALGORITHM_VERSIONS
            and self.matching_jobs is not None
            else self.jobs
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
        modern = self.algorithm_version in {
            "c-recommendation/lexicographic/v3",
            "c-recommendation/lexicographic/v4",
            "c-recommendation/lexicographic/v5",
            "c-recommendation/lexicographic/v6",
            "c-recommendation/lexicographic/v7",
            NEW_SKILL_ALGORITHM_VERSION,
        }
        # 순서 규칙은 계산과 따로 움직인다. Trend tie-break 는 후보 자격도
        # `increased_count` 도 바꾸지 않으므로 `algorithm_version` 을 올리지 않고
        # 여기서 갈린다. 대신 어느 규칙으로 정렬했는지가 payload 에 남아야 같은
        # v7 아래의 두 순서 의미가 섞이지 않는다.
        impact_version = self.algorithm_version == NEW_SKILL_ALGORITHM_VERSION
        allowed_rules = (
            {IMPACT_TIE_BREAK_RULE, IMPACT_TREND_TIE_BREAK_RULE}
            if impact_version
            else {TIE_BREAK_RULE, TREND_TIE_BREAK_RULE}
            if modern
            else {LEGACY_TIE_BREAK_RULE}
        )
        if self.tie_break_rule not in allowed_rules:
            raise ValueError("recommendation formula and rank policy mismatch")
        # `modern` 과 같은 범위다. Trend 순서 규칙은 계산과 직교하므로 v3 이후의
        # 어떤 계산에도 붙을 수 있지만, legacy 순서 규칙을 쓰는 v1/v2 결과에는
        # 붙을 수 없다 -- 그 결과들은 저장된 순서를 그대로 읽기만 한다.
        if self.tie_break_rule == TREND_TIE_BREAK_RULE and not modern:
            raise ValueError("trend tie-break requires a v3 or newer calculation")
        # 근거가 있는데 규칙이 예전 것이면, 저장된 순서를 그 근거로 재현할 수 없다.
        # 반대 방향은 막지 않는다 -- 규칙만 있고 근거가 없는 것은 "적용하려 했으나
        # 게시된 주차가 없었다"는 실제로 일어나는 사실이다.
        if self.trend_tiebreak is not None and self.tie_break_rule not in {
            TREND_TIE_BREAK_RULE,
            IMPACT_TREND_TIE_BREAK_RULE,
        }:
            raise ValueError("trend basis requires the trend tie-break rank policy")
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
            self.schema_version
            != (
                "recommendation-snapshot/v4"
                if impact_version
                else "recommendation-snapshot/v3"
            )
            or self.evidence_input_version is None
            or self.matching_jobs is None
        ):
            raise ValueError("v6 recommendation requires expanded matching inputs")
        if not expanded and self.matching_jobs is not None:
            raise ValueError("expanded matching inputs require recommendation v6")
        calculation_jobs = self.calculation_jobs
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
        new_skill_policy = self.algorithm_version in {
            "c-recommendation/lexicographic/v7",
            NEW_SKILL_ALGORITHM_VERSION,
        }
        for candidate in self.candidates:
            if not _is_candidate_eligible(
                candidate.tech_id,
                new_skill_policy=new_skill_policy,
                level_aware=level_aware,
                missing_tech_ids=self.gap.missing_tech_ids,
                personal_levels=self.personal_levels,
            ):
                raise ValueError("candidate must be an evaluated missing technology")
            if impact_version:
                if candidate.what_if is not None or candidate.impact is None:
                    raise ValueError("v8 candidate requires condition impact only")
                expected_impact = condition_impact(
                    self.matching_jobs or (),
                    frozenset(self.held.held_tech_ids),
                    self.personal_levels,
                    candidate.tech_id,
                    self.cohort_id,
                )
                if candidate.impact != expected_impact:
                    raise ValueError(
                        "candidate impact must use snapshot cohort and evidence"
                    )
                continue
            if candidate.impact is not None or candidate.what_if is None:
                raise ValueError("legacy candidate requires What-if only")
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


def _reordered_by_trend(
    top3: list[tuple[tuple, dict]],
    trend_lookup: "Callable[[tuple[str, ...]], TrendTieBreakBasis | None] | None",
) -> tuple[list[tuple[tuple, dict]], "TrendTieBreakBasis | None"]:
    """Reorder the settled Top3 inside near-tie clusters; never re-select.

    `key[0]` 은 구 버전에서는 `-increased_count`, v8에서는
    `-affected_count`다. 나머지 키는 해당 버전의 동률 순서다.
    무리 안에서는 앞자리만 Trend 로 갈리고 나머지는 그대로 이어진다.

    조회는 **여기서 한 번** 일어난다. 후보마다 부르지 않으므로 추천 한 건이
    네트워크를 세 번 왕복하는 일이 없다.
    """
    tech_ids = tuple(payload["tech_id"] for _, payload in top3)
    if trend_lookup is None or len(top3) < 2:
        return top3, None
    basis = trend_lookup(tech_ids)
    if basis is None:
        return top3, None
    if not set(basis.values) <= set(tech_ids):
        # 묻지 않은 기술의 값이 섞이면 저장된 근거가 저장된 순서를 설명하지 못한다.
        raise ValueError("trend basis must answer only the Top3 technologies")
    by_tech = {payload["tech_id"]: (key, payload) for key, payload in top3}
    reordered = apply_trend_tiebreak(
        tuple(
            TieBreakCandidate(
                tech_id=payload["tech_id"],
                increased_count=-key[0],
                rest_key=tuple(key[1:]),
            )
            for key, payload in top3
        ),
        basis.values,
    )
    return [by_tech[item.tech_id] for item in reordered], basis


def build_recommendations(
    cohort: JobCohort,
    analysis: EvidenceAnalysis,
    *,
    user_id: str,
    analysis_id: str,
    demand_snapshot: DemandSnapshot | None = None,
    prerequisites: PrerequisiteSnapshot | None = None,
    trend_lookup: Callable[[tuple[str, ...]], "TrendTieBreakBasis | None"]
    | None = None,
) -> RecommendationSnapshot:
    """Rank at most three missing technologies; all counts share one cohort.

    UNKNOWN is excluded from the missing-candidate pool.

    `trend_lookup` 은 **Top3 가 정해진 뒤에** 그 세 `tech_id` 로만 호출된다
    (S15P21E102-355). 값이 아니라 조회 함수를 받는 것은 후보가 정해지기 전에는
    무엇을 물어야 할지 알 수 없고, 후보 풀 전체를 묻는 것은 bounded 조회가 아니기
    때문이다. 후보 자격·1차 영향 건수는 이 값을 보지 않으므로 Trend 가
    후보를 고르는 일은 없다.
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
    calculated_demand = aggregate_demand(cohort)
    if demand_snapshot is not None:
        # Projection restores only the selected matching rows. Its paired Demand
        # snapshot still carries the full input/excluded/review accounting that
        # the legacy cohort computed before narrowing the rows. The recommendation
        # may reuse those scope counts only when every calculation-bearing field
        # agrees with the restored cohort.
        ignored_scope_counts = {
            "input_count",
            "excluded_count",
            "review_count",
        }
        calculated_basis = calculated_demand.model_dump(mode="json")
        resolved_basis = demand_snapshot.model_dump(mode="json")
        for field in ignored_scope_counts:
            calculated_basis.pop(field, None)
            resolved_basis.pop(field, None)
        if calculated_basis != resolved_basis:
            raise ValueError("resolved Demand does not match the recommendation cohort")
        demand = demand_snapshot
    else:
        demand = calculated_demand
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
    if demand.review_count:
        data_gaps.add(f"COHORT_RECORDS_REQUIRE_REVIEW:{demand.review_count}")
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
    new_skill_policy = algorithm_version in {
        "c-recommendation/lexicographic/v7",
        NEW_SKILL_ALGORITHM_VERSION,
    }

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
        impact = (
            condition_impact(
                cohort.matching_jobs,
                frozenset(held.held_tech_ids),
                personal_levels,
                row.tech_id,
                cohort.cohort_id,
            )
            if expanded and cohort.matching_jobs is not None
            else None
        )
        what_if = None
        if impact is None:
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
        if impact is not None:
            reasons.add(
                "DIRECT_CONDITION_IMPACT"
                if impact.affected_count
                else "NO_DIRECT_CONDITION_IMPACT"
            )
        else:
            reasons.add(
                "DIRECT_JOB_INCREASE"
                if what_if is not None and what_if.increased_count
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
        affected_job_ids = (
            impact.affected_job_ids
            if impact is not None
            else what_if.newly_matched_job_ids
            if what_if is not None
            else ()
        )
        fact_ids = {
            f"demand:{cohort.cohort_id}:{row.tech_id}",
            f"evidence:{analysis.analysis_id}:{row.tech_id}",
            f"{'impact' if impact is not None else 'what-if'}:{cohort.cohort_id}:{row.tech_id}",
            *(f"job:{cohort.cohort_id}:{job_id}" for job_id in affected_job_ids),
        }
        if rule:
            fact_ids.update(rule.fact_ids)
        uncertainty = len(unknown) + len(decisions[row.tech_id].data_gaps)
        key = (
            (
                -impact.affected_count,
                -impact.required_count,
                bool(missing or unknown),
                -row.required_count,
                uncertainty,
                -row.total_count,
                row.tech_id,
            )
            if impact is not None
            else (
                -what_if.increased_count,
                bool(missing or unknown),
                -row.required_count,
                uncertainty,
                -row.total_count,
                row.tech_id,
            )
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
                    "impact": impact,
                },
            )
        )
    # Top3 는 기존 비교 키가 고른다. Trend 는 그 다음이다 -- 두 단계를 한 정렬로
    # 합치면 4위 후보가 Trend 만으로 Top3 에 들어올 수 있고, 그것은 순서 보정이
    # 아니라 후보 선정이다(S15P21E102-355).
    top3 = sorted(ranked, key=lambda item: item[0])[:3]
    top3, trend_tiebreak = _reordered_by_trend(top3, trend_lookup)
    candidates = tuple(
        RecommendationCandidate(rank=rank, **payload)
        for rank, (_, payload) in enumerate(top3, start=1)
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
    if expanded:
        tie_break_rule = (
            IMPACT_TREND_TIE_BREAK_RULE
            if trend_tiebreak is not None
            else IMPACT_TIE_BREAK_RULE
        )
    elif algorithm_version in {
        "c-recommendation/lexicographic/v3",
        "c-recommendation/lexicographic/v4",
        "c-recommendation/lexicographic/v5",
        "c-recommendation/lexicographic/v6",
        "c-recommendation/lexicographic/v7",
    }:
        tie_break_rule = (
            TREND_TIE_BREAK_RULE if trend_tiebreak is not None else TIE_BREAK_RULE
        )
    else:
        tie_break_rule = LEGACY_TIE_BREAK_RULE
    content = _RecommendationContent(
        schema_version=(
            "recommendation-snapshot/v4" if expanded else "recommendation-snapshot/v2"
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
        tie_break_rule=tie_break_rule,
        trend_tiebreak=trend_tiebreak,
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
    view: Literal["CURRENT", "WHAT_IF", "IMPACT"]
    tech_id: TechId | None
    impact_kind: Literal["ALL", "REQUIRED", "PREFERRED"] | None = None
    total_count: StrictInt = Field(ge=0)
    offset: StrictInt = Field(ge=0)
    limit: StrictInt = Field(ge=1, le=100)
    current_count: StrictInt | None = Field(default=None, ge=0)
    projected_count: StrictInt | None = Field(default=None, ge=0)
    increased_count: StrictInt | None = Field(default=None, ge=0)
    impact_counts: dict[str, StrictInt] | None = None
    impact_job_kinds: dict[NonBlank, tuple[Literal["REQUIRED", "PREFERRED"], ...]] = (
        Field(default_factory=dict)
    )
    items: tuple[CohortJob | MatchingJobInput, ...]
    data_gaps: tuple[NonBlank, ...]


def snapshot_from_stored_payload(
    payload: Mapping[str, object],
) -> RecommendationSnapshot:
    """Read a persisted recommendation, ignoring metadata stored beside it.

    S15P21E102-368. The writer keeps `cohort_snapshot_id`, `explanation`,
    `job_matching`/`job_matching_ref` and `projection_version_id` in the same
    JSON row as the model fields, and the model is `extra="forbid"`. Readers
    used to drop those keys by name, so the projection rollout's new key turned
    every What-if detail read into a `ValidationError` -- reported as
    `INVALID_INPUT` and shown to users as an unsupported role or filter.

    Selecting the model's own fields cannot go stale the way a deny list does.
    It narrows the input only: a missing or malformed field still fails, and
    `RecommendationSnapshot.model_validate` keeps forbidding extras for callers
    that hold a payload which is supposed to be exactly the model.
    """

    return RecommendationSnapshot.model_validate(
        {
            name: value
            for name, value in payload.items()
            if name in RecommendationSnapshot.model_fields
        }
    )


def list_related_jobs(
    snapshot: RecommendationSnapshot,
    *,
    user_id: str,
    view: Literal["CURRENT", "WHAT_IF", "IMPACT"],
    tech_id: str | None = None,
    impact_kind: Literal["ALL", "REQUIRED", "PREFERRED"] = "ALL",
    offset: int = 0,
    limit: int = 20,
    active_job_ids: AbstractSet[str] | None = None,
) -> RelatedJobsPage:
    """Page legacy full-match IDs or v8 resolved-clause impact IDs."""
    if snapshot.user_id != user_id:
        raise PermissionError("recommendation snapshot belongs to another user")
    if (
        type(offset) is not int
        or type(limit) is not int
        or offset < 0
        or not 1 <= limit <= 100
    ):
        raise ValueError("offset must be nonnegative and limit must be in 1..100")
    current_ids = tuple(
        job_id
        for job_id in snapshot.current_job_ids
        if active_job_ids is None or job_id in active_job_ids
    )
    impact_counts = None
    impact_job_kinds = {}
    if view == "CURRENT":
        if tech_id is not None:
            raise ValueError("CURRENT list does not take a candidate technology")
        ids, projected_count, increased_count = (
            current_ids,
            len(current_ids),
            0,
        )
    elif view == "WHAT_IF":
        candidate = next(
            (item for item in snapshot.candidates if item.tech_id == tech_id), None
        )
        if candidate is None or candidate.what_if is None:
            raise ValueError("WHAT_IF list requires a candidate in this snapshot")
        ids = tuple(
            job_id
            for job_id in candidate.what_if.newly_matched_job_ids
            if active_job_ids is None or job_id in active_job_ids
        )
        projected_ids = tuple(
            job_id
            for job_id in candidate.what_if.projected_job_ids
            if active_job_ids is None or job_id in active_job_ids
        )
        projected_count, increased_count = (
            len(projected_ids),
            len(ids),
        )
    elif view == "IMPACT":
        candidate = next(
            (item for item in snapshot.candidates if item.tech_id == tech_id), None
        )
        if candidate is None or candidate.impact is None:
            raise ValueError("IMPACT list requires a v8 candidate in this snapshot")
        impact = active_condition_impact(candidate.impact, active_job_ids)
        ids = {
            "ALL": impact.affected_job_ids,
            "REQUIRED": impact.required_job_ids,
            "PREFERRED": impact.preferred_job_ids,
        }[impact_kind]
        impact_counts = {
            "required_count": impact.required_count,
            "preferred_count": impact.preferred_count,
            "affected_count": impact.affected_count,
        }
        for job_id in ids[offset : offset + limit]:
            impact_job_kinds[job_id] = tuple(
                kind
                for kind, member_ids in (
                    ("REQUIRED", impact.required_job_ids),
                    ("PREFERRED", impact.preferred_job_ids),
                )
                if job_id in member_ids
            )
        projected_count = increased_count = None
    else:
        raise ValueError("view must be CURRENT, WHAT_IF, or IMPACT")
    jobs = {job.job_id: job for job in snapshot.calculation_jobs}
    return RelatedJobsPage(
        snapshot_id=snapshot.snapshot_id,
        cohort_id=snapshot.cohort_id,
        view=view,
        tech_id=tech_id,
        impact_kind=impact_kind if view == "IMPACT" else None,
        total_count=len(ids),
        offset=offset,
        limit=limit,
        current_count=None if view == "IMPACT" else len(current_ids),
        projected_count=projected_count,
        increased_count=increased_count,
        impact_counts=impact_counts,
        impact_job_kinds=impact_job_kinds,
        items=tuple(jobs[job_id] for job_id in ids[offset : offset + limit]),
        data_gaps=snapshot.data_gaps,
    )
