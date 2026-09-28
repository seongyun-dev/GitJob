"""Monthly posted-job trend over comparable MONTHLY_DEMAND snapshots."""

import math

from job.cohort import CohortPurpose, CohortStatus
from job.demand import DemandSnapshot
from registry.contracts import TechnologyRegistry
from registry.mapper import RegistryMapper
from trend.contracts import (
    TrendPoint,
    TrendResult,
    TrendStatus,
    compare_points,
    validate_periods,
)

JOB_TREND_POLICY_VERSION = "c-job-monthly-demand/v2"
FILTER_FIELDS = ("target_role", "sources", "regions", "career_levels", "min_jobs")
VERSION_FIELDS = (
    "registry_version",
    "parser_version",
    "quality_version",
    "aggregation_version",
)


def _period(snapshot: DemandSnapshot) -> str:
    if snapshot.criteria.purpose is not CohortPurpose.MONTHLY_DEMAND:
        raise ValueError("MONTHLY_DEMAND_COHORT_REQUIRED")
    return snapshot.criteria.complete_month()


def _validate_counts(snapshot: DemandSnapshot) -> None:
    if snapshot.denominator == 0 and snapshot.status is not CohortStatus.EMPTY:
        raise ValueError("INVALID_DENOMINATOR_STATUS")
    if snapshot.status is CohortStatus.EMPTY and snapshot.denominator != 0:
        raise ValueError("INVALID_DENOMINATOR_STATUS")
    if (
        snapshot.status is CohortStatus.READY
        and snapshot.denominator < snapshot.criteria.min_jobs
    ):
        raise ValueError("INVALID_DENOMINATOR_STATUS")
    tech_ids = set()
    for row in snapshot.technologies:
        if row.tech_id in tech_ids:
            raise ValueError("DUPLICATE_TECHNOLOGY")
        tech_ids.add(row.tech_id)
        if snapshot.denominator == 0 or row.total_count > snapshot.denominator:
            raise ValueError("NUMERATOR_EXCEEDS_DENOMINATOR")
        if (
            row.total_count
            > row.required_count + row.preferred_count + row.general_count
        ):
            raise ValueError("INCONSISTENT_DEMAND_COUNTS")
        for category in ("required", "preferred", "general", "total"):
            count, ratio = (
                getattr(row, f"{category}_count"),
                getattr(row, f"{category}_ratio"),
            )
            if count > row.total_count or not math.isclose(
                ratio, count / snapshot.denominator, rel_tol=1e-9, abs_tol=1e-12
            ):
                raise ValueError("INCONSISTENT_DEMAND_COUNTS")


def job_trend(
    tech_id: str,
    snapshots: tuple[DemandSnapshot, ...] | None,
    registry: TechnologyRegistry,
    *,
    periods: tuple[str, ...],
) -> TrendResult:
    indices = validate_periods(periods, quarterly=False)
    common = {
        "source": "JOB",
        "tech_id": tech_id,
        "metric": "distinct_posting_count",
        "unit": "POSTINGS",
        "granularity": "MONTH",
        "registry_version": registry.registry_version,
        "algorithm_version": JOB_TREND_POLICY_VERSION,
    }
    if not RegistryMapper(registry).has_active_technology(tech_id):
        return TrendResult(
            **common, status=TrendStatus.NOT_SUPPORTED, reasons=("UNKNOWN_TECHNOLOGY",)
        )
    if snapshots is None:
        return TrendResult(
            **common, status=TrendStatus.PREPARING, reasons=("INPUT_NOT_AVAILABLE",)
        )
    by_period = {}
    reference = None
    try:
        for snapshot in snapshots:
            period = _period(snapshot)
            if period not in periods:
                continue
            if period in by_period:
                raise ValueError("DUPLICATE_MONTH")
            if snapshot.registry_version != registry.registry_version:
                raise ValueError("REGISTRY_VERSION_MISMATCH")
            filters = {name: getattr(snapshot.criteria, name) for name in FILTER_FIELDS}
            identity = (
                filters,
                tuple(getattr(snapshot, name) for name in VERSION_FIELDS),
            )
            if reference is not None and reference != identity:
                raise ValueError("COHORT_FILTER_OR_VERSION_MISMATCH")
            reference = identity
            _validate_counts(snapshot)
            by_period[period] = snapshot
    except ValueError as exc:
        return TrendResult(**common, status=TrendStatus.FAILED, reasons=(str(exc),))
    points = []
    for period in periods:
        snapshot = by_period.get(period)
        if snapshot is None:
            points.append(
                TrendPoint(period=period, reasons=("MONTH_SNAPSHOT_MISSING",))
            )
            continue
        row = next(
            (row for row in snapshot.technologies if row.tech_id == tech_id), None
        )
        count = row.total_count if row else 0
        points.append(
            TrendPoint(
                period=period,
                value=count if snapshot.denominator else None,
                denominator=snapshot.denominator,
                ratio=count / snapshot.denominator if snapshot.denominator else None,
                reasons=()
                if snapshot.status is CohortStatus.READY
                else ("COHORT_INSUFFICIENT",),
                source_version=snapshot.aggregation_version,
                input_run_id=snapshot.pipeline_run_id,
                dataset_snapshot_id=snapshot.dataset_snapshot_id,
                collector_version=snapshot.collector_version,
                cohort_id=snapshot.cohort_id,
                as_of=snapshot.criteria.as_of.isoformat(),
                excluded_count=snapshot.excluded_count,
                review_count=snapshot.review_count,
            )
        )
    output = compare_points(tuple(points), indices)
    complete = (
        len(output) >= 2
        and all(
            p.value is not None and "COHORT_INSUFFICIENT" not in p.reasons
            for p in output
        )
        and all(indices[i] == indices[i - 1] + 1 for i in range(1, len(indices)))
    )
    filters = {
        **(reference[0] if reference else {}),
        "timezone": "Asia/Seoul",
        "month_end": "exclusive",
        "purpose": CohortPurpose.MONTHLY_DEMAND.value,
        "date_basis": "SOURCE_POSTED_OR_MODIFIED",
        "posting_status_policy": "INCLUDE_CLOSED",
    }
    if reference:
        filters["versions"] = dict(zip(VERSION_FIELDS, reference[1], strict=True))
    return TrendResult(
        **common,
        status=TrendStatus.READY if complete else TrendStatus.INSUFFICIENT_DATA,
        reasons=() if complete else ("MISSING_PERIOD_OR_VALID_COHORT_OR_BASELINE",),
        points=output,
        filters=filters,
    )
