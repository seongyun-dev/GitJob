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

from job.requirements import (
    JobRequirements,
    RequirementClause,
    RequirementKind,
    UnresolvedRequirement,
)
from recommendation.evidence import EvidenceAnalysis, HeldStatus, consume_evidence

if TYPE_CHECKING:
    from job.cohort import JobCohort

JOB_MATCHING_VERSION = "job-matching/v2"
JOB_MATCHING_STORAGE_VERSION = "job-matching-storage/v2"
MAX_MATCHING_JOBS = 50_000
MAX_MATCHING_RESULT_BYTES = 64 * 1024 * 1024
MAX_MATCHING_SOURCE_BYTES = 512 * 1024
MAX_MATCHING_ASSESSMENT_BYTES = 64 * 1024
RATIO_ABSOLUTE_TOLERANCE = 5e-7

CalculationId = StringConstraints(strict=True, pattern=r"^matching-[0-9a-f]{64}$")
MatchingJobId = StringConstraints(strict=True, min_length=1, max_length=256)


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

    @model_validator(mode="after")
    def check_partition(self):
        groups = (self.held_tech_ids, self.missing_tech_ids, self.unknown_tech_ids)
        flat = [item for group in groups for item in group]
        if len(flat) != len(set(flat)) or set(flat) != set(self.clause.tech_ids):
            raise ValueError("clause evidence partition mismatch")
        expected = (
            "SATISFIED"
            if self.held_tech_ids
            else "UNKNOWN"
            if self.unknown_tech_ids
            else "UNSATISFIED"
        )
        if self.status != expected:
            raise ValueError("clause status mismatch")
        return self


def evaluate_clause(
    clause: RequirementClause, decisions: dict[str, HeldStatus]
) -> ClauseAssessment:
    groups = {status: [] for status in HeldStatus}
    for tech_id in clause.tech_ids:
        groups[decisions.get(tech_id, HeldStatus.UNKNOWN)].append(tech_id)
    held, missing, unknown = (
        tuple(sorted(groups[status]))
        for status in (HeldStatus.HELD, HeldStatus.NOT_HELD, HeldStatus.UNKNOWN)
    )
    return ClauseAssessment(
        clause=clause,
        status="SATISFIED" if held else "UNKNOWN" if unknown else "UNSATISFIED",
        held_tech_ids=held,
        missing_tech_ids=missing,
        unknown_tech_ids=unknown,
    )


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


def _conditions(clauses, unresolved, decisions):
    evaluated = tuple(evaluate_clause(clause, decisions) for clause in clauses)
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
    if value.unresolved or value.unknown_count:
        return "UNKNOWN"
    if not value.clauses:
        return "NOT_APPLICABLE"
    if not value.unsatisfied_count:
        return "FULL"
    return "PARTIAL" if value.satisfied_count else "NONE"


class JobAssessment(MatchingModel):
    job: MatchingJobInput
    required: ConditionAssessment
    preferred: ConditionAssessment
    required_status: Literal["FULL", "PARTIAL", "NONE", "UNKNOWN", "NOT_APPLICABLE"]

    @model_validator(mode="after")
    def check_status(self):
        if self.required_status != _required_status(self.required):
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
    ranks = {"FULL": 0, "PARTIAL": 1, "NONE": 2, "UNKNOWN": 3, "NOT_APPLICABLE": 4}
    return (
        row.job.eligibility != "ELIGIBLE",
        ranks[row.required_status],
        -(row.required.fulfillment_ratio or 0),
        -row.preferred.satisfied_count,
        row.job.job_id,
    )


class JobMatchingResult(MatchingModel):
    schema_version: Literal["job-matching/v1", "job-matching/v2"] = JOB_MATCHING_VERSION
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
        if len(self.jobs) > MAX_MATCHING_JOBS:
            raise MatchingResultTooLarge(
                f"matching result exceeds {MAX_MATCHING_JOBS} jobs"
            )
        if len({item.job.job_id for item in self.jobs}) != len(self.jobs):
            raise ValueError("duplicate partial matching job")
        if self.jobs != tuple(sorted(self.jobs, key=_job_sort)):
            raise ValueError("partial matching must have stable ordering")
        canonical = self.model_dump(mode="json", exclude={"calculation_snapshot_id"})
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


class StoredConditionAssessment(MatchingModel):
    clauses: tuple[StoredClauseAssessment, ...]
    satisfied_count: StrictInt = Field(ge=0)
    unsatisfied_count: StrictInt = Field(ge=0)
    unknown_count: StrictInt = Field(ge=0)


class StoredJobAssessment(MatchingModel):
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
            )
            for item in value.clauses
        ),
        satisfied_count=value.satisfied_count,
        unsatisfied_count=value.unsatisfied_count,
        unknown_count=value.unknown_count,
    )


def compact_job_assessment(value: JobAssessment) -> dict[str, Any]:
    """Keep only user-specific decisions; clauses/evidence live in matching_source."""
    return StoredJobAssessment(
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
    return JobAssessment(
        job=job,
        required=_restore_condition(
            stored.required, job.requirements.required, required_unresolved
        ),
        preferred=_restore_condition(
            stored.preferred, job.requirements.preferred, preferred_unresolved
        ),
        required_status=stored.required_status,
    )


def matching_storage_rows(result: JobMatchingResult) -> dict[str, Any]:
    """Build bounded shared-source and per-user rows for one atomic publication."""
    sources, assessments = [], []
    total_bytes = 0
    for position, row in enumerate(result.jobs):
        source = row.job.model_dump(mode="json")
        assessment = compact_job_assessment(row)
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
        )
        preferred = _conditions(
            job.requirements.preferred,
            tuple(
                item
                for item in job.requirements.unresolved
                if item.requirement_kind == RequirementKind.PREFERRED
            ),
            decisions,
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
        "user_id": user_id,
        "analysis_id": analysis_id,
        "cohort_id": cohort.cohort_id,
        "registry_version": cohort.registry_version,
        "held_policy_version": selection.held_policy_version,
        "level_policy_version": analysis.level_policy_version,
        "evidence_rule_version": analysis.evidence_rule_version,
        "criteria": cohort.criteria.model_dump(mode="json"),
        "strict_cohort_status": cohort.status.value,
        "data_gaps": selection.data_gaps,
        "jobs": tuple(sorted(rows, key=_job_sort)),
    }
    return JobMatchingResult(**content)
