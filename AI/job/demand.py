"""Distinct posting demand over an immutable, purpose-specific quality cohort."""

from typing import Literal

from pydantic import Field, StrictInt, StrictStr, model_validator

from job.classifier import MatchStatus, RequirementClass
from job.cohort import (
    MARKET_SCOPE_EXCLUSIONS,
    CohortCriteria,
    CohortModel,
    CohortPurpose,
    CohortStatus,
    JobCohort,
)
from job.cross_site_identity import canonical_identities
from registry.contracts import TechId

JOB_DEMAND_AGGREGATION_VERSION = "job-demand-aggregation/v4"


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
    # CURRENT_MARKET에서 JobKorea↔Saramin 동일 공고로 판정되어 합쳐지면서
    # **strict 모집단**이 줄어든 수 (S15P21E102-352). 시장 전체 병합 수가 아니다 —
    # 제외된 공고끼리의 병합까지 세면 그 공고들을 말하지 않는 불변식에 슬랙만 준다.
    #
    # 0이면 직렬화에서 빠진다. Recommendation snapshot 의 id 는 내용 해시이므로
    # 필드가 하나 늘면 합쳐진 것이 없는 과거 snapshot 까지 id 가 어긋난다.
    cross_site_merged_count: StrictInt = Field(
        default=0, ge=0, exclude_if=lambda value: value == 0
    )
    dataset_snapshot_id: StrictStr
    pipeline_run_id: StrictStr
    collector_version: StrictStr
    registry_version: StrictStr
    parser_version: StrictStr
    quality_version: StrictStr
    aggregation_version: StrictStr = JOB_DEMAND_AGGREGATION_VERSION
    # Projection previews expose their immutable basis additively. Legacy
    # Snapshot payloads omit it and continue to validate unchanged.
    projection_version_id: StrictStr | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    technologies: tuple[TechnologyDemand, ...]

    @model_validator(mode="after")
    def validate_distinct_counts(self) -> "DemandSnapshot":
        if self.status is not CohortStatus.for_size(
            self.denominator, self.criteria.min_jobs
        ):
            raise ValueError("demand status must reflect denominator and min_jobs")
        strict_count = (
            self.input_count
            - self.duplicate_count
            - self.excluded_count
            - self.review_count
        )
        if strict_count < 0:
            raise ValueError("demand counts do not reconcile")
        if (
            self.aggregation_version
            in {"job-demand-aggregation/v3", "job-demand-aggregation/v4"}
            and (self.criteria.purpose is CohortPurpose.ACTIVE_MATCHING)
            and self.matching_count is not None
        ):
            if (
                self.matching_count != self.denominator
                or strict_count > self.denominator
                or self.denominator > self.input_count
            ):
                raise ValueError("active demand must use the matching population")
        elif self.criteria.purpose is CohortPurpose.CURRENT_MARKET:
            # 시장 분모는 품질 제외/검토를 포함하므로 strict 집합보다 크고, 재전달
            # 중복과 선언한 범위 밖 공고를 뺀 만큼 input_count보다 작다.
            if (
                self.matching_count is not None
                or strict_count - self.cross_site_merged_count > self.denominator
                or self.denominator > self.input_count - self.duplicate_count
            ):
                raise ValueError("market demand must use every in-scope posting")
        else:
            if strict_count != self.denominator:
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


def _demand_rows(
    counts: dict[str, dict[str, set[str]]], denominator: int
) -> tuple[TechnologyDemand, ...]:
    """Rank by posting count descending, then tech_id, for every category."""

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
    return tuple(rows)


def _aggregate_current_market(cohort: JobCohort) -> DemandSnapshot:
    """Count every valid distinct posting we hold, included or not.

    The market population is ``jobs + exclusions`` because a posting that failed
    the role or quality gate still occupies the market. Only Registry-resolved
    REQUIRED/PREFERRED observations are counted: an unmapped mention has no
    stable identity to rank, and a MENTIONED one is a sighting rather than a
    requirement. Postings whose requirements never resolved stay in the
    denominator so the ratio is not inflated by shrinking it.

    S15P21E102-352: one job advertised on both JobKorea and Saramin was two
    postings here, inflating the denominator and every per-technology count.
    High-confidence cross-site pairs now share one identity for this count only
    — the rows keep their own `source_site`/`source_posting_id`, and
    ACTIVE_MATCHING is not reached by this function at all.
    """

    market_rows = [
        item
        for item in (*cohort.jobs, *cohort.exclusions)
        # 선언한 범위 밖이거나 기준 시각에 관측되지 않은 공고는 시장이 아니다.
        if not MARKET_SCOPE_EXCLUSIONS.intersection(getattr(item, "reasons", ()))
    ]
    canonical = canonical_identities(market_rows)

    def _identity(item) -> str:
        return canonical.get(
            (item.source_site, item.source_posting_id),
            f"{item.source_site}:{item.source_posting_id}",
        )

    # `strict_count` in the validator counts the strictly included postings, so
    # the number reported here is the merges *within that set* — not every merge
    # in the market. Counting all of them would let a merge between two excluded
    # postings buy slack in an invariant that says nothing about them.
    strict_keys = {(job.source_site, job.source_posting_id) for job in cohort.jobs}
    strict_rows = [
        row
        for row in market_rows
        if (row.source_site, row.source_posting_id) in strict_keys
    ]
    merged_strict = len(
        {(row.source_site, row.source_posting_id) for row in strict_rows}
    ) - len({_identity(row) for row in strict_rows})

    counts: dict[str, dict[str, set[str]]] = {}
    postings: set[str] = set()
    for item in market_rows:
        # 같은 공고가 다른 source_record_id로 다시 들어와도 한 건이다.
        posting_id = _identity(item)
        postings.add(posting_id)
        categories: dict[str, set[str]] = {
            "required": set(),
            "preferred": set(),
            "general": set(),
        }
        for observation in item.technologies:
            if (
                observation.tech_id is None
                or observation.match_status is not MatchStatus.MATCHED
            ):
                continue
            if observation.requirement_class is RequirementClass.REQUIRED:
                categories["required"].add(observation.tech_id)
            elif observation.requirement_class is RequirementClass.PREFERRED:
                categories["preferred"].add(observation.tech_id)
        for category, tech_ids in categories.items():
            for tech_id in tech_ids:
                counts.setdefault(
                    tech_id,
                    {
                        name: set()
                        for name in ("required", "preferred", "general", "total")
                    },
                )
                counts[tech_id][category].add(posting_id)
                counts[tech_id]["total"].add(posting_id)
    denominator = len(postings)
    metadata = cohort.model_dump(
        exclude={"schema_version", "jobs", "exclusions", "input_union", "matching_jobs"}
    )
    metadata["status"] = CohortStatus.for_size(denominator, cohort.criteria.min_jobs)
    return DemandSnapshot(
        **metadata,
        denominator=denominator,
        matching_count=None,
        cross_site_merged_count=merged_strict,
        technologies=_demand_rows(counts, denominator),
    )


def aggregate_demand(cohort: JobCohort) -> DemandSnapshot:
    """Count an OR alternative as a mentioned required option, not an AND gate.

    Ratios are fractions in [0, 1]. Rank is total_count descending then tech_id
    ascending. Requirement categories overlap, so total uses their set union.
    """
    counts: dict[str, dict[str, set[str]]] = {}
    active_matching = (
        cohort.criteria.purpose is CohortPurpose.ACTIVE_MATCHING
        and cohort.matching_jobs is not None
    )
    if cohort.criteria.purpose is CohortPurpose.CURRENT_MARKET:
        return _aggregate_current_market(cohort)
    population = cohort.matching_jobs if active_matching else cohort.jobs
    strict_by_id = {job.job_id: job for job in cohort.jobs}
    assert population is not None
    for job in population:
        if active_matching:
            strict = strict_by_id.get(job.job_id)
            categories = {
                "required": {
                    tech_id
                    for clause in job.requirements.required
                    for tech_id in clause.tech_ids
                },
                "preferred": {
                    tech_id
                    for clause in job.requirements.preferred
                    for tech_id in clause.tech_ids
                },
                # GENERAL은 기존 strict 공고에 보존된 분류만 사용한다. 미확정 공고의
                # 언급을 필수/우대로 승격하지 않는다.
                "general": set(strict.general_tech_ids)
                if strict is not None
                else set(),
            }
        else:
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
    denominator = len(population)
    rows = _demand_rows(counts, denominator)
    metadata = cohort.model_dump(
        exclude={"schema_version", "jobs", "exclusions", "input_union", "matching_jobs"}
    )
    if active_matching:
        metadata["status"] = CohortStatus.for_size(
            denominator, cohort.criteria.min_jobs
        )
    return DemandSnapshot(
        **metadata,
        denominator=denominator,
        matching_count=denominator if active_matching else None,
        technologies=tuple(rows),
    )
