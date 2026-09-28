"""Versioned partial requirement assessment, independent of recommendation ranks."""

import json
import math
from datetime import datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)
from recommendation.evidence import (
    EvidenceAnalysis,
    HeldStatus,
    consume_evidence,
    consume_personal_assessments,
    consume_personal_level_scope_complete_tech_ids,
    consume_personal_levels,
)

from job.requirements import (
    JobRequirements,
    RequirementClause,
    RequirementKind,
    RequirementLevel,
    UnresolvedRequirement,
)

if TYPE_CHECKING:
    from job.cohort import JobCohort

JOB_MATCHING_VERSION = "job-matching/v3"
JOB_MATCHING_STORAGE_VERSION = "job-matching-storage/v2"
MAX_MATCHING_JOBS = 50_000
MAX_MATCHING_RESULT_BYTES = 64 * 1024 * 1024
MAX_MATCHING_SOURCE_BYTES = 512 * 1024
MAX_MATCHING_ASSESSMENT_BYTES = 64 * 1024
RATIO_ABSOLUTE_TOLERANCE = 5e-7

CalculationId = StringConstraints(strict=True, pattern=r"^matching-[0-9a-f]{64}$")
MatchingJobId = StringConstraints(strict=True, min_length=1, max_length=256)
EvidenceInputVersion = Literal[
    "evidence-consumption-input/v1",
    "evidence-consumption-input/v2",
    "evidence-consumption-input/v3",
    "evidence-consumption-input/v4",
]


class MatchingResultTooLarge(ValueError):
    """A complete result exceeded a published budget and was not truncated."""


class MatchingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MatchingJobInput(MatchingModel):
    job_id: Annotated[str, MatchingJobId]
    source_record_id: StrictStr
    source_site: StrictStr
    source_posting_id: StrictStr
    source_url: HttpUrl
    company_name: StrictStr
    title: StrictStr
    region: StrictStr | None = None
    career_level: StrictStr | None = None
    deadline: datetime | None = None
    collected_at: datetime
    content_hash: StrictStr
    eligibility: Literal["ELIGIBLE", "CONDITIONAL"]
    eligibility_reasons: tuple[StrictStr, ...] = ()
    strict_match_eligible: StrictBool
    strict_review_reasons: tuple[StrictStr, ...] = ()
    requirements: JobRequirements

    @model_validator(mode="after")
    def check_source(self):
        if (
            self.source_record_id != self.requirements.source_record_id
            or self.content_hash != self.requirements.content_hash
        ):
            raise ValueError("matching requirements source mismatch")
        if (self.eligibility == "CONDITIONAL") != bool(self.eligibility_reasons):
            raise ValueError("conditional eligibility requires reasons")
        if self.strict_match_eligible and self.eligibility != "ELIGIBLE":
            raise ValueError("conditional job cannot be strictly eligible")
        if self.strict_match_eligible == bool(self.strict_review_reasons):
            raise ValueError("strict eligibility must explain all review reasons")
        return self


class ClauseAssessment(MatchingModel):
    clause: RequirementClause
    status: Literal["SATISFIED", "UNSATISFIED", "UNKNOWN"]
    held_tech_ids: tuple[StrictStr, ...]
    missing_tech_ids: tuple[StrictStr, ...]
    unknown_tech_ids: tuple[StrictStr, ...]
    verdict: (
        Literal[
            "SATISFIED",
            "LEGACY_HELD_MATCH",
            "LEVEL_BELOW_REQUIRED",
            "TECHNOLOGY_NOT_HELD",
            "EVIDENCE_SCOPE_INCOMPLETE",
        ]
        | None
    ) = Field(default=None, exclude_if=lambda value: value is None)
    personal_levels: dict[StrictStr, Literal["L0", "L1", "L2", "L3"]] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )
    assessment_ceilings: dict[StrictStr, Literal["L0", "L1", "L2", "L3"]] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )
    level_assessment_complete_tech_ids: tuple[StrictStr, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    assessment_ceiling_applied: StrictBool = False

    @model_validator(mode="after")
    def check_partition(self):
        groups = (self.held_tech_ids, self.missing_tech_ids, self.unknown_tech_ids)
        flat = [item for group in groups for item in group]
        if len(flat) != len(set(flat)) or set(flat) != set(self.clause.tech_ids):
            raise ValueError("clause evidence partition mismatch")
        if self.level_assessment_complete_tech_ids != tuple(
            sorted(set(self.level_assessment_complete_tech_ids))
        ):
            raise ValueError("complete level assessments must be unique and sorted")
        if not self.assessment_ceiling_applied and self.assessment_ceilings:
            raise ValueError("assessment ceilings require ceiling-aware mode")
        if self.clause.required_level is not None and self.verdict is None:
            raise ValueError("levelled clause requires a verdict")
        if self.clause.required_level is None and (
            self.verdict is not None
            or self.personal_levels
            or self.assessment_ceilings
            or self.level_assessment_complete_tech_ids
            or self.assessment_ceiling_applied
        ):
            raise ValueError("unlevelled clause cannot carry level assessment metadata")
        if self.verdict is not None:
            if self.clause.required_level is None:
                raise ValueError("level verdict requires a required level")
            if not set(self.personal_levels) <= set(self.held_tech_ids):
                raise ValueError("personal levels require held technologies")
            if not set(self.assessment_ceilings) <= set(self.held_tech_ids):
                raise ValueError("assessment ceilings require held technologies")
            if not set(self.level_assessment_complete_tech_ids) <= set(
                self.held_tech_ids
            ):
                raise ValueError("complete level assessments require held technologies")
            if any(
                _level_rank(level) > _level_rank(self.assessment_ceilings.get(tech))
                for tech, level in self.personal_levels.items()
                if tech in self.assessment_ceilings
            ):
                raise ValueError("personal level is above assessment ceiling")
            qualifies = any(
                _level_at_least(
                    self.personal_levels.get(tech), self.clause.required_level
                )
                for tech in self.held_tech_ids
            )
            conclusively_below = bool(self.held_tech_ids) and all(
                tech in self.personal_levels
                and tech in self.level_assessment_complete_tech_ids
                and (
                    not self.assessment_ceiling_applied
                    or (
                        _level_at_least(
                            self.assessment_ceilings.get(tech),
                            self.clause.required_level,
                        )
                    )
                )
                for tech in self.held_tech_ids
            )
            if self.verdict == "SATISFIED" and not qualifies:
                raise ValueError("satisfied level verdict requires a qualifying level")
            if self.verdict == "LEGACY_HELD_MATCH" and (
                not self.held_tech_ids
                or self.personal_levels
                or self.assessment_ceilings
                or self.level_assessment_complete_tech_ids
                or self.assessment_ceiling_applied
            ):
                raise ValueError("legacy held verdict cannot claim a personal level")
            if self.verdict == "LEVEL_BELOW_REQUIRED" and (
                bool(self.unknown_tech_ids) or not conclusively_below or qualifies
            ):
                raise ValueError("below-level verdict does not match evidence")
            if self.verdict == "TECHNOLOGY_NOT_HELD" and (
                self.held_tech_ids or self.unknown_tech_ids or self.personal_levels
            ):
                raise ValueError("not-held verdict does not match evidence")
            if self.verdict == "EVIDENCE_SCOPE_INCOMPLETE" and (
                qualifies
                or not (
                    self.unknown_tech_ids
                    or (self.held_tech_ids and not conclusively_below)
                )
            ):
                raise ValueError("incomplete verdict does not match evidence")
        expected = (
            "SATISFIED"
            if self.verdict in {"SATISFIED", "LEGACY_HELD_MATCH"}
            else "UNKNOWN"
            if self.verdict == "EVIDENCE_SCOPE_INCOMPLETE"
            else "UNSATISFIED"
            if self.verdict
            else "SATISFIED"
            if self.held_tech_ids
            else "UNKNOWN"
            if self.unknown_tech_ids
            else "UNSATISFIED"
        )
        if self.status != expected:
            raise ValueError("clause status mismatch")
        return self


def evaluate_clause(
    clause: RequirementClause,
    decisions: dict[str, HeldStatus],
    personal_levels: dict[str, str] | None = None,
    assessment_ceilings: dict[str, str] | None = None,
    level_assessment_complete_tech_ids: frozenset[str] = frozenset(),
) -> ClauseAssessment:
    groups = {status: [] for status in HeldStatus}
    for tech_id in clause.tech_ids:
        groups[decisions.get(tech_id, HeldStatus.UNKNOWN)].append(tech_id)
    held, missing, unknown = (
        tuple(sorted(groups[status]))
        for status in (HeldStatus.HELD, HeldStatus.NOT_HELD, HeldStatus.UNKNOWN)
    )
    levels = personal_levels or {}
    level_values = (
        {key: levels[key] for key in clause.tech_ids if key in levels}
        if clause.required_level is not None
        else {}
    )
    ceilings = assessment_ceilings or {}
    ceiling_values = (
        {key: ceilings[key] for key in clause.tech_ids if key in ceilings}
        if clause.required_level is not None
        else {}
    )
    complete_ids = (
        tuple(sorted(set(clause.tech_ids) & level_assessment_complete_tech_ids))
        if clause.required_level is not None
        else ()
    )
    ceiling_aware = (
        assessment_ceilings is not None and clause.required_level is not None
    )
    if clause.required_level is None:
        verdict = None
    elif personal_levels is None:
        verdict = (
            "LEGACY_HELD_MATCH"
            if held
            else "EVIDENCE_SCOPE_INCOMPLETE"
            if unknown
            else "TECHNOLOGY_NOT_HELD"
        )
    elif any(
        decisions.get(tech, HeldStatus.UNKNOWN) is HeldStatus.HELD
        and _level_at_least(levels.get(tech), clause.required_level)
        for tech in clause.tech_ids
    ):
        verdict = "SATISFIED"
    elif (
        unknown
        or any(tech not in levels for tech in held)
        or any(tech not in level_assessment_complete_tech_ids for tech in held)
        or (
            ceiling_aware
            and any(
                not _level_at_least(ceilings.get(tech), clause.required_level)
                for tech in held
            )
        )
    ):
        verdict = "EVIDENCE_SCOPE_INCOMPLETE"
    elif held:
        verdict = "LEVEL_BELOW_REQUIRED"
    else:
        verdict = "TECHNOLOGY_NOT_HELD"
    return ClauseAssessment(
        clause=clause,
        status="SATISFIED"
        if verdict in {"SATISFIED", "LEGACY_HELD_MATCH"}
        else "UNKNOWN"
        if verdict == "EVIDENCE_SCOPE_INCOMPLETE"
        else "UNSATISFIED"
        if verdict
        else "SATISFIED"
        if held
        else "UNKNOWN"
        if unknown
        else "UNSATISFIED",
        held_tech_ids=held,
        missing_tech_ids=missing,
        unknown_tech_ids=unknown,
        verdict=verdict,
        personal_levels=level_values,
        assessment_ceilings=ceiling_values,
        level_assessment_complete_tech_ids=complete_ids,
        assessment_ceiling_applied=ceiling_aware,
    )


def _level_at_least(value: str | None, required: RequirementLevel) -> bool:
    return (
        _level_rank(value)
        >= {
            RequirementLevel.L1: 1,
            RequirementLevel.L2: 2,
            RequirementLevel.L3: 3,
        }[required]
    )


def _level_rank(value: str | None) -> int:
    return {"L0": 0, "L1": 1, "L2": 2, "L3": 3}.get(value, -1)


class ConditionAssessment(MatchingModel):
    clauses: tuple[ClauseAssessment, ...]
    unresolved: tuple[UnresolvedRequirement, ...]
    satisfied_count: StrictInt = Field(ge=0)
    unsatisfied_count: StrictInt = Field(ge=0)
    unknown_count: StrictInt = Field(ge=0)
    fulfillment_ratio: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def check_counts(self):
        counts = {
            status: sum(item.status == status for item in self.clauses)
            for status in ("SATISFIED", "UNSATISFIED", "UNKNOWN")
        }
        if (self.satisfied_count, self.unsatisfied_count, self.unknown_count) != (
            counts["SATISFIED"],
            counts["UNSATISFIED"],
            counts["UNKNOWN"],
        ):
            raise ValueError("condition counts mismatch")
        expected = (
            self.satisfied_count / len(self.clauses)
            if self.clauses and not self.unresolved and not self.unknown_count
            else None
        )
        supplied = self.fulfillment_ratio
        if expected is None:
            if supplied is not None:
                raise ValueError("unconfirmed conditions cannot claim a complete ratio")
        elif (
            supplied is None
            or not math.isfinite(supplied)
            or not math.isclose(
                supplied, expected, rel_tol=0, abs_tol=RATIO_ABSOLUTE_TOLERANCE
            )
        ):
            raise ValueError("unconfirmed conditions cannot claim a complete ratio")
        else:
            # Integer counts are canonical. Tolerated transport rounding never changes IDs.
            object.__setattr__(self, "fulfillment_ratio", expected)
        return self


def _conditions(
    clauses,
    unresolved,
    decisions,
    personal_levels=None,
    assessment_ceilings=None,
    level_assessment_complete_tech_ids=frozenset(),
):
    evaluated = tuple(
        evaluate_clause(
            clause,
            decisions,
            personal_levels,
            assessment_ceilings,
            level_assessment_complete_tech_ids,
        )
        for clause in clauses
    )
    satisfied = sum(item.status == "SATISFIED" for item in evaluated)
    unknown = sum(item.status == "UNKNOWN" for item in evaluated)
    return ConditionAssessment(
        clauses=evaluated,
        unresolved=tuple(unresolved),
        satisfied_count=satisfied,
        unsatisfied_count=sum(item.status == "UNSATISFIED" for item in evaluated),
        unknown_count=unknown,
        fulfillment_ratio=satisfied / len(evaluated)
        if evaluated and not unknown and not unresolved
        else None,
    )


def _required_status(value: ConditionAssessment) -> str:
    if not value.clauses:
        return "UNKNOWN" if value.unresolved else "NOT_APPLICABLE"
    if value.satisfied_count:
        if value.unsatisfied_count or value.unknown_count or value.unresolved:
            return "PARTIAL"
        return "FULL"
    if value.unknown_count or value.unresolved:
        return "UNKNOWN"
    return "NONE"


class JobAssessment(MatchingModel):
    job: MatchingJobInput
    required: ConditionAssessment
    preferred: ConditionAssessment
    required_status: Literal["FULL", "PARTIAL", "NONE", "UNKNOWN", "NOT_APPLICABLE"]

    @model_validator(mode="after")
    def check_status(self):
        expected = _required_status(self.required)
        legacy_unknown = self.required_status == "UNKNOWN" and expected == "PARTIAL"
        if self.required_status != expected and not legacy_unknown:
            raise ValueError("required status mismatch")
        for kind, assessed, source in (
            (RequirementKind.REQUIRED, self.required, self.job.requirements.required),
            (
                RequirementKind.PREFERRED,
                self.preferred,
                self.job.requirements.preferred,
            ),
        ):
            if tuple(
                item.clause for item in assessed.clauses
            ) != source or assessed.unresolved != tuple(
                item
                for item in self.job.requirements.unresolved
                if item.requirement_kind == kind
            ):
                raise ValueError("assessment must preserve its source requirements")
        return self


def _job_sort(row: JobAssessment):
    # The user's observed match comes before parser completeness. A posting with
    # one satisfied known clause plus an unresolved remainder is PARTIAL and
    # must not be hidden below a fully parsed posting whose known clauses are
    # all unsatisfied (NONE).
    ranks = {"FULL": 0, "PARTIAL": 1, "UNKNOWN": 2, "NONE": 3, "NOT_APPLICABLE": 4}
    return (
        row.job.eligibility != "ELIGIBLE",
        ranks[row.required_status],
        row.required.unsatisfied_count,
        -row.required.satisfied_count,
        row.required.unknown_count + len(row.required.unresolved),
        -row.preferred.satisfied_count,
        row.job.job_id,
    )


def _legacy_job_sort(row: JobAssessment):
    ranks = {"FULL": 0, "PARTIAL": 1, "NONE": 2, "UNKNOWN": 3, "NOT_APPLICABLE": 4}
    return (
        row.job.eligibility != "ELIGIBLE",
        ranks[row.required_status],
        -(row.required.fulfillment_ratio or 0),
        -row.preferred.satisfied_count,
        row.job.job_id,
    )


class JobMatchingResult(MatchingModel):
    schema_version: Literal["job-matching/v1", "job-matching/v2", "job-matching/v3"] = (
        JOB_MATCHING_VERSION
    )
    evidence_input_version: EvidenceInputVersion | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    calculation_snapshot_id: Annotated[str, CalculationId] = ""
    user_id: StrictStr
    analysis_id: StrictStr
    cohort_id: StrictStr
    registry_version: StrictStr
    held_policy_version: StrictStr
    level_policy_version: StrictStr
    evidence_rule_version: StrictStr
    criteria: dict[str, Any]
    strict_cohort_status: StrictStr
    data_gaps: tuple[StrictStr, ...]
    jobs: tuple[JobAssessment, ...]

    @model_validator(mode="after")
    def check_jobs(self):
        if (
            self.schema_version in {"job-matching/v2", "job-matching/v3"}
            and self.evidence_input_version is None
        ):
            raise ValueError("current job matching requires an evidence input version")
        if len(self.jobs) > MAX_MATCHING_JOBS:
            raise MatchingResultTooLarge(
                f"matching result exceeds {MAX_MATCHING_JOBS} jobs"
            )
        if len({item.job.job_id for item in self.jobs}) != len(self.jobs):
            raise ValueError("duplicate partial matching job")
        if self.schema_version == "job-matching/v3" and any(
            item.required_status != _required_status(item.required)
            for item in self.jobs
        ):
            raise ValueError("required status mismatch")
        sort_key = (
            _job_sort if self.schema_version == "job-matching/v3" else _legacy_job_sort
        )
        if self.jobs != tuple(sorted(self.jobs, key=sort_key)):
            raise ValueError("partial matching must have stable ordering")
        canonical = _matching_calculation_payload(self)
        expected = _calculation_id(canonical)
        if self.calculation_snapshot_id and self.calculation_snapshot_id != expected:
            raise ValueError("matching calculation ID mismatch")
        object.__setattr__(self, "calculation_snapshot_id", expected)
        return self

    @property
    def calculation_id(self):
        return self.calculation_snapshot_id


class StoredClauseAssessment(MatchingModel):
    status: Literal["SATISFIED", "UNSATISFIED", "UNKNOWN"]
    held_tech_ids: tuple[StrictStr, ...]
    missing_tech_ids: tuple[StrictStr, ...]
    unknown_tech_ids: tuple[StrictStr, ...]
    verdict: (
        Literal[
            "SATISFIED",
            "LEGACY_HELD_MATCH",
            "LEVEL_BELOW_REQUIRED",
            "TECHNOLOGY_NOT_HELD",
            "EVIDENCE_SCOPE_INCOMPLETE",
        ]
        | None
    ) = None
    personal_levels: dict[StrictStr, Literal["L0", "L1", "L2", "L3"]] = Field(
        default_factory=dict
    )
    assessment_ceilings: dict[StrictStr, Literal["L0", "L1", "L2", "L3"]] = Field(
        default_factory=dict
    )
    level_assessment_complete_tech_ids: tuple[StrictStr, ...] = ()
    assessment_ceiling_applied: StrictBool = False


class StoredConditionAssessment(MatchingModel):
    clauses: tuple[StoredClauseAssessment, ...]
    satisfied_count: StrictInt = Field(ge=0)
    unsatisfied_count: StrictInt = Field(ge=0)
    unknown_count: StrictInt = Field(ge=0)


class StoredJobAssessment(MatchingModel):
    evidence_input_version: EvidenceInputVersion | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    required: StoredConditionAssessment
    preferred: StoredConditionAssessment
    required_status: Literal["FULL", "PARTIAL", "NONE", "UNKNOWN", "NOT_APPLICABLE"]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _calculation_id(value: dict[str, Any]) -> str:
    return "matching-" + sha256(_canonical_bytes(value)).hexdigest()


def _matching_calculation_payload(result: JobMatchingResult) -> dict[str, Any]:
    canonical = result.model_dump(mode="json", exclude={"calculation_snapshot_id"})
    if result.schema_version != "job-matching/v1":
        return canonical

    # job-matching/v1 predates level-aware clause metadata. Pydantic injects the
    # new false default while reading an old embedded result, so remove only that
    # absent historical field before checking the immutable calculation ID.
    for job in canonical["jobs"]:
        for condition_name in ("required", "preferred"):
            for clause in job[condition_name]["clauses"]:
                clause.pop("assessment_ceiling_applied", None)
    return canonical


def validate_job_matching(value: dict[str, Any]) -> JobMatchingResult:
    """Read embedded v1 results without changing their historical hash identity."""
    jobs = value.get("jobs")
    if isinstance(jobs, (list, tuple)) and len(jobs) > MAX_MATCHING_JOBS:
        raise MatchingResultTooLarge(
            f"matching result exceeds {MAX_MATCHING_JOBS} jobs"
        )
    if len(_canonical_bytes(value)) > MAX_MATCHING_RESULT_BYTES:
        raise MatchingResultTooLarge(
            f"embedded matching result exceeds {MAX_MATCHING_RESULT_BYTES} bytes"
        )
    return JobMatchingResult.model_validate(value)


def matching_reference(
    result: JobMatchingResult, *, cohort_snapshot_id: str
) -> dict[str, Any]:
    return {
        "schema_version": JOB_MATCHING_STORAGE_VERSION,
        "calculation_snapshot_id": result.calculation_snapshot_id,
        "cohort_snapshot_id": cohort_snapshot_id,
        "job_count": len(result.jobs),
    }


def _stored_condition(value: ConditionAssessment) -> StoredConditionAssessment:
    return StoredConditionAssessment(
        clauses=tuple(
            StoredClauseAssessment(
                status=item.status,
                held_tech_ids=item.held_tech_ids,
                missing_tech_ids=item.missing_tech_ids,
                unknown_tech_ids=item.unknown_tech_ids,
                verdict=item.verdict,
                personal_levels=item.personal_levels,
                assessment_ceilings=item.assessment_ceilings,
                level_assessment_complete_tech_ids=(
                    item.level_assessment_complete_tech_ids
                ),
                assessment_ceiling_applied=item.assessment_ceiling_applied,
            )
            for item in value.clauses
        ),
        satisfied_count=value.satisfied_count,
        unsatisfied_count=value.unsatisfied_count,
        unknown_count=value.unknown_count,
    )


def compact_job_assessment(
    value: JobAssessment, *, evidence_input_version: EvidenceInputVersion
) -> dict[str, Any]:
    """Keep only user-specific decisions; clauses/evidence live in matching_source."""
    return StoredJobAssessment(
        evidence_input_version=evidence_input_version,
        required=_stored_condition(value.required),
        preferred=_stored_condition(value.preferred),
        required_status=value.required_status,
    ).model_dump(mode="json")


def _restore_condition(
    stored: StoredConditionAssessment,
    clauses: tuple[RequirementClause, ...],
    unresolved: tuple[UnresolvedRequirement, ...],
) -> ConditionAssessment:
    if len(stored.clauses) != len(clauses):
        raise ValueError("stored clause reference count mismatch")
    assessments = tuple(
        ClauseAssessment(clause=clause, **decision.model_dump(mode="json"))
        for clause, decision in zip(clauses, stored.clauses, strict=True)
    )
    ratio = (
        stored.satisfied_count / len(assessments)
        if assessments and not unresolved and not stored.unknown_count
        else None
    )
    return ConditionAssessment(
        clauses=assessments,
        unresolved=unresolved,
        satisfied_count=stored.satisfied_count,
        unsatisfied_count=stored.unsatisfied_count,
        unknown_count=stored.unknown_count,
        fulfillment_ratio=ratio,
    )


def restore_job_assessment(
    source: dict[str, Any], assessment: dict[str, Any]
) -> JobAssessment:
    job = MatchingJobInput.model_validate(source)
    stored = StoredJobAssessment.model_validate(assessment)
    if (
        stored.evidence_input_version is None
        and job.requirements.schema_version != "job-requirements/v1"
    ):
        raise ValueError(
            "stored evidence input version is required for levelled requirements"
        )
    required_unresolved = tuple(
        item
        for item in job.requirements.unresolved
        if item.requirement_kind == RequirementKind.REQUIRED
    )
    preferred_unresolved = tuple(
        item
        for item in job.requirements.unresolved
        if item.requirement_kind == RequirementKind.PREFERRED
    )
    if stored.evidence_input_version == "evidence-consumption-input/v4":
        for condition, clauses in (
            (stored.required, job.requirements.required),
            (stored.preferred, job.requirements.preferred),
        ):
            for decision, clause in zip(condition.clauses, clauses):
                if (
                    clause.required_level is not None
                    and not decision.assessment_ceiling_applied
                ):
                    raise ValueError("v4 stored clause requires ceiling-aware mode")
    restored = JobAssessment(
        job=job,
        required=_restore_condition(
            stored.required, job.requirements.required, required_unresolved
        ),
        preferred=_restore_condition(
            stored.preferred, job.requirements.preferred, preferred_unresolved
        ),
        required_status=stored.required_status,
    )
    for condition in (restored.required, restored.preferred):
        for clause in condition.clauses:
            if clause.clause.required_level is None:
                continue
            if stored.evidence_input_version == "evidence-consumption-input/v4":
                if not clause.assessment_ceiling_applied:
                    raise ValueError("v4 stored clause requires ceiling-aware mode")
            elif clause.assessment_ceiling_applied:
                raise ValueError("legacy stored clause cannot use ceiling-aware mode")
            if (
                stored.evidence_input_version
                not in {
                    "evidence-consumption-input/v1",
                    "evidence-consumption-input/v2",
                }
                and clause.verdict == "LEGACY_HELD_MATCH"
            ):
                raise ValueError("legacy held verdict requires evidence input v1 or v2")
            if stored.evidence_input_version in {
                "evidence-consumption-input/v1",
                "evidence-consumption-input/v2",
            } and clause.verdict not in {
                "LEGACY_HELD_MATCH",
                "TECHNOLOGY_NOT_HELD",
                "EVIDENCE_SCOPE_INCOMPLETE",
            }:
                raise ValueError("legacy stored clause has a personal-level verdict")
    return restored


def matching_storage_rows(result: JobMatchingResult) -> dict[str, Any]:
    """Build bounded shared-source and per-user rows for one atomic publication."""
    if result.evidence_input_version is None:
        raise ValueError("matching storage requires an evidence input version")
    sources, assessments = [], []
    total_bytes = 0
    for position, row in enumerate(result.jobs):
        source = row.job.model_dump(mode="json")
        assessment = compact_job_assessment(
            row, evidence_input_version=result.evidence_input_version
        )
        source_bytes = len(_canonical_bytes(source))
        assessment_bytes = len(_canonical_bytes(assessment))
        if source_bytes > MAX_MATCHING_SOURCE_BYTES:
            raise MatchingResultTooLarge("matching source row exceeds its byte budget")
        if assessment_bytes > MAX_MATCHING_ASSESSMENT_BYTES:
            raise MatchingResultTooLarge(
                "matching assessment row exceeds its byte budget"
            )
        total_bytes += source_bytes + assessment_bytes
        if total_bytes > MAX_MATCHING_RESULT_BYTES:
            raise MatchingResultTooLarge(
                f"matching result exceeds {MAX_MATCHING_RESULT_BYTES} stored bytes"
            )
        sources.append(source)
        assessments.append(
            {
                "position": position,
                "job_id": row.job.job_id,
                "eligibility": row.job.eligibility,
                "assessment": assessment,
            }
        )
    metadata = result.model_dump(
        mode="json", exclude={"jobs", "calculation_snapshot_id"}
    )
    return {
        "calculation_snapshot_id": result.calculation_snapshot_id,
        "metadata": metadata,
        "sources": sources,
        "assessments": assessments,
        "total_count": len(result.jobs),
        "eligible_count": sum(row.job.eligibility == "ELIGIBLE" for row in result.jobs),
        "conditional_count": sum(
            row.job.eligibility == "CONDITIONAL" for row in result.jobs
        ),
        "stored_bytes": total_bytes,
    }


def build_job_matching(
    cohort: "JobCohort", analysis: EvidenceAnalysis, *, user_id: str, analysis_id: str
) -> JobMatchingResult:
    from job.cohort import CohortPurpose

    if cohort.criteria.purpose != CohortPurpose.ACTIVE_MATCHING:
        raise ValueError("ACTIVE_MATCHING_COHORT_REQUIRED")
    if cohort.registry_version != analysis.registry_version:
        raise ValueError("Registry versions must match for matching")
    if cohort.matching_jobs is None:
        raise ValueError("MATCHING_INPUT_NOT_PREPARED")
    if len(cohort.matching_jobs) > MAX_MATCHING_JOBS:
        raise MatchingResultTooLarge(
            f"matching result exceeds {MAX_MATCHING_JOBS} jobs"
        )
    ids = {
        tech
        for job in cohort.matching_jobs
        for clause in (*job.requirements.required, *job.requirements.preferred)
        for tech in clause.tech_ids
    }
    selection = consume_evidence(
        analysis, user_id=user_id, analysis_id=analysis_id, tech_ids=ids
    )
    decisions = {key: item.status for key, item in selection.by_tech_id.items()}
    (
        personal_levels,
        assessment_ceilings,
        level_assessment_complete_tech_ids,
    ) = _validated_personal_assessments(analysis, selection, ids)
    rows = []
    for job in cohort.matching_jobs:
        required = _conditions(
            job.requirements.required,
            tuple(
                item
                for item in job.requirements.unresolved
                if item.requirement_kind == RequirementKind.REQUIRED
            ),
            decisions,
            personal_levels,
            assessment_ceilings,
            level_assessment_complete_tech_ids,
        )
        preferred = _conditions(
            job.requirements.preferred,
            tuple(
                item
                for item in job.requirements.unresolved
                if item.requirement_kind == RequirementKind.PREFERRED
            ),
            decisions,
            personal_levels,
            assessment_ceilings,
            level_assessment_complete_tech_ids,
        )
        rows.append(
            JobAssessment(
                job=job,
                required=required,
                preferred=preferred,
                required_status=_required_status(required),
            )
        )
    content = {
        "schema_version": JOB_MATCHING_VERSION,
        "evidence_input_version": analysis.schema_version,
        "user_id": user_id,
        "analysis_id": analysis_id,
        "cohort_id": cohort.cohort_id,
        "registry_version": cohort.registry_version,
        "held_policy_version": selection.held_policy_version,
        "level_policy_version": analysis.level_policy_version,
        "evidence_rule_version": analysis.evidence_rule_version,
        "criteria": cohort.criteria.model_dump(mode="json"),
        "strict_cohort_status": cohort.status.value,
        "data_gaps": tuple(sorted(set(selection.data_gaps) | _level_data_gaps(rows))),
        "jobs": tuple(sorted(rows, key=_job_sort)),
    }
    return JobMatchingResult(**content)


def _validated_personal_assessments(
    analysis: EvidenceAnalysis, selection, tech_ids: set[str] | None = None
) -> tuple[
    dict[str, str] | None,
    dict[str, str] | None,
    frozenset[str],
]:
    """Return the versioned personal axis without evidence-level fallbacks.

    The existing evidence_level remains a repository-evidence compatibility
    field.  It is deliberately not a fallback for personal_level.
    """
    if analysis.schema_version == "evidence-consumption-input/v3":
        return (
            consume_personal_levels(analysis, selection),
            None,
            consume_personal_level_scope_complete_tech_ids(analysis, selection),
        )
    if analysis.schema_version == "evidence-consumption-input/v4":
        assessments = consume_personal_assessments(analysis, selection)
        if tech_ids is not None:
            assessments = {
                key: item for key, item in assessments.items() if key in tech_ids
            }
        return (
            {key: item.personal_level for key, item in assessments.items()},
            {key: item.assessment_ceiling for key, item in assessments.items()},
            frozenset(key for key, item in assessments.items() if item.scope_complete),
        )
    else:
        # Old B envelopes predate an explicit personal axis. Preserve their
        # historical held-only matching rather than treating evidence_level as
        # a personal level or rewriting old snapshot meaning.
        return None, None, frozenset()


def _level_data_gaps(rows: list[JobAssessment]) -> set[str]:
    gaps: set[str] = set()
    for row in rows:
        for condition in (row.required, row.preferred):
            for assessment in condition.clauses:
                if assessment.verdict != "EVIDENCE_SCOPE_INCOMPLETE":
                    continue
                required = assessment.clause.required_level
                if required is None:  # Guard the persisted invariant for type checkers.
                    continue
                for tech in assessment.held_tech_ids:
                    if tech not in assessment.personal_levels:
                        gaps.add(f"PERSONAL_LEVEL_UNCONFIRMED:{tech}")
                    elif assessment.assessment_ceiling_applied and (
                        tech not in assessment.assessment_ceilings
                    ):
                        gaps.add(f"PERSONAL_LEVEL_ASSESSMENT_UNCONFIRMED:{tech}")
                    elif assessment.assessment_ceiling_applied and not _level_at_least(
                        assessment.assessment_ceilings[tech], required
                    ):
                        gaps.add(
                            "ASSESSMENT_CEILING_BELOW_REQUIREMENT:"
                            f"{tech}:{required.value}"
                        )
                    elif assessment.assessment_ceiling_applied and tech not in set(
                        assessment.level_assessment_complete_tech_ids
                    ):
                        gaps.add(f"PERSONAL_LEVEL_SCOPE_INCOMPLETE:{tech}")
    return gaps
