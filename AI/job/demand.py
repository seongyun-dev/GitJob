"""Distinct posting demand over an immutable, purpose-specific quality cohort."""

from typing import Literal

from pydantic import Field, StrictInt, StrictStr, model_validator

from job.cohort import CohortCriteria, CohortModel, CohortStatus, JobCohort
from registry.contracts import TechId

JOB_DEMAND_AGGREGATION_VERSION = "job-demand-aggregation/v2"


class TechnologyDemand(CohortModel):
    tech_id: TechId
    required_count: StrictInt = Field(ge=0)
    preferred_count: StrictInt = Field(ge=0)
    general_count: StrictInt = Field(ge=0)
    total_count: StrictInt = Field(ge=0)
    required_ratio: float = Field(ge=0, le=1)
    preferred_ratio: float = Field(ge=0, le=1)
    general_ratio: float = Field(ge=0, le=1)
    total_ratio: float = Field(ge=0, le=1)
    rank: StrictInt = Field(ge=1)
    required_rank: StrictInt | None = Field(default=None, ge=1)
    preferred_rank: StrictInt | None = Field(default=None, ge=1)
    general_rank: StrictInt | None = Field(default=None, ge=1)
    total_rank: StrictInt | None = Field(default=None, ge=1)


class DemandSnapshot(CohortModel):
    schema_version: Literal["job-demand-snapshot/v1"] = "job-demand-snapshot/v1"
    cohort_id: StrictStr
    status: CohortStatus
    criteria: CohortCriteria
    denominator: StrictInt = Field(ge=0)
    # ACTIVE_MATCHING에서 직무·상태·지역·경력 필터를 통과해 상세 비교에 남은 공고.
    # 과거 snapshot과 MONTHLY_DEMAND에는 필드가 없으므로 additive nullable이다.
    matching_count: StrictInt | None = Field(
        default=None, ge=0, exclude_if=lambda value: value is None
    )
    input_count: StrictInt = Field(ge=0)
    duplicate_count: StrictInt = Field(ge=0)
    excluded_count: StrictInt = Field(ge=0)
    review_count: StrictInt = Field(ge=0)
    dataset_snapshot_id: StrictStr
    pipeline_run_id: StrictStr
    collector_version: StrictStr
    registry_version: StrictStr
    parser_version: StrictStr
    quality_version: StrictStr
    aggregation_version: StrictStr = JOB_DEMAND_AGGREGATION_VERSION
    technologies: tuple[TechnologyDemand, ...]

    @model_validator(mode="after")
    def validate_distinct_counts(self) -> "DemandSnapshot":
        if self.status is not CohortStatus.for_size(
            self.denominator, self.criteria.min_jobs
        ):
            raise ValueError("demand status must reflect denominator and min_jobs")
        if (
            self.input_count
            != self.denominator
            + self.duplicate_count
            + self.excluded_count
            + self.review_count
        ):
            raise ValueError("demand counts do not reconcile")
        if self.matching_count is not None and not (
            self.denominator <= self.matching_count <= self.input_count
        ):
            raise ValueError("matching count must contain the strict denominator")
        if len({item.tech_id for item in self.technologies}) != len(self.technologies):
            raise ValueError("demand technology IDs must be unique")
        for item in self.technologies:
            categories = (item.required_count, item.preferred_count, item.general_count)
            if (
                not max(categories)
                <= item.total_count
                <= min(sum(categories), self.denominator)
            ):
                raise ValueError(
                    "total count must be a distinct category union within denominator"
                )
            if self.denominator == 0:
                raise ValueError("empty demand must not contain technology rows")
            for name in ("required", "preferred", "general", "total"):
                if (
                    getattr(item, f"{name}_ratio")
                    != getattr(item, f"{name}_count") / self.denominator
                ):
                    raise ValueError("demand ratios must use the cohort denominator")
        return self


def aggregate_demand(cohort: JobCohort) -> DemandSnapshot:
    """Count an OR alternative as a mentioned required option, not an AND gate.

    Ratios are fractions in [0, 1]. Rank is total_count descending then tech_id
    ascending. Requirement categories overlap, so total uses their set union.
    """
    counts: dict[str, dict[str, set[str]]] = {}
    for job in cohort.jobs:
        categories = {
            "required": {
                tech_id for clause in job.required_clauses for tech_id in clause
            },
            "preferred": set(job.preferred_tech_ids),
            # The classifier SKILL field is explicitly adapted to GENERAL in
            # CohortJob.general_tech_ids. The A contract stays MENTIONED.
            "general": set(job.general_tech_ids),
        }
        for category, tech_ids in categories.items():
            for tech_id in tech_ids:
                counts.setdefault(
                    tech_id,
                    {
                        name: set()
                        for name in ("required", "preferred", "general", "total")
                    },
                )
                counts[tech_id][category].add(job.job_id)
                counts[tech_id]["total"].add(job.job_id)
    denominator = len(cohort.jobs)
    ranks = {
        category: {
            tech_id: rank
            for rank, (tech_id, _) in enumerate(
                sorted(
                    (
                        (tech_id, ids)
                        for tech_id, ids in counts.items()
                        if ids[category]
                    ),
                    key=lambda item: (-len(item[1][category]), item[0]),
                ),
                start=1,
            )
        }
        for category in ("required", "preferred", "general", "total")
    }
    rows = []
    for rank, (tech_id, category_ids) in enumerate(
        sorted(counts.items(), key=lambda item: (-len(item[1]["total"]), item[0])),
        start=1,
    ):
        values = {
            f"{category}_count": len(ids) for category, ids in category_ids.items()
        }
        ratios = {
            f"{category}_ratio": len(ids) / denominator
            for category, ids in category_ids.items()
        }
        category_ranks = {
            f"{category}_rank": ranking.get(tech_id)
            for category, ranking in ranks.items()
        }
        rows.append(
            TechnologyDemand(
                tech_id=tech_id, rank=rank, **values, **ratios, **category_ranks
            )
        )
    metadata = cohort.model_dump(
        exclude={"schema_version", "jobs", "exclusions", "input_union", "matching_jobs"}
    )
    return DemandSnapshot(
        **metadata,
        denominator=denominator,
        matching_count=(
            len(cohort.matching_jobs) if cohort.matching_jobs is not None else None
        ),
        technologies=tuple(rows),
    )
