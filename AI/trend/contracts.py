"""Shared serialized output for quarterly GitHub and monthly job observations."""

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

TREND_VERSION = "c-source-trend/v1"


class TrendStatus(StrEnum):
    READY = "READY"
    PREPARING = "PREPARING"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    FAILED = "FAILED"


class TrendPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    period: str
    value: int | None = Field(default=None, ge=0)
    denominator: int | None = Field(default=None, ge=0)
    ratio: float | None = Field(default=None, ge=0, le=1)
    absolute_change: int | None = None
    relative_change: float | None = None
    ratio_change: float | None = None
    reasons: tuple[str, ...] = ()
    source_version: str | None = None
    source_uri: str | None = None
    input_run_id: str | None = None
    dataset_snapshot_id: str | None = None
    collector_version: str | None = None
    cohort_id: str | None = None
    as_of: str | None = None
    excluded_count: int | None = Field(default=None, ge=0)
    review_count: int | None = Field(default=None, ge=0)


class TrendResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = TREND_VERSION
    source: str
    tech_id: str
    metric: str
    unit: str
    granularity: str
    status: TrendStatus
    reasons: tuple[str, ...] = ()
    points: tuple[TrendPoint, ...] = ()
    registry_version: str
    algorithm_version: str = TREND_VERSION
    source_hash: str | None = None
    filters: dict[str, object] = Field(default_factory=dict)


def validate_periods(periods: tuple[str, ...], *, quarterly: bool) -> tuple[int, ...]:
    pattern = r"([0-9]{4})-Q([1-4])" if quarterly else r"([0-9]{4})-(0[1-9]|1[0-2])"
    indices = []
    if not periods:
        raise ValueError("at least one explicit period is required")
    for period in periods:
        match = re.fullmatch(pattern, period)
        if not match or int(match[1]) < 2020:
            raise ValueError("invalid trend period")
        indices.append(int(match[1]) * (4 if quarterly else 12) + int(match[2]))
    if indices != sorted(set(indices)):
        raise ValueError("periods must be unique and ascending")
    return tuple(indices)


def compare_points(
    points: tuple[TrendPoint, ...], indices: tuple[int, ...]
) -> tuple[TrendPoint, ...]:
    output = []
    for i, point in enumerate(points):
        prior = points[i - 1] if i and indices[i] == indices[i - 1] + 1 else None
        reasons = list(point.reasons)
        changes = {}
        if point.value is not None:
            if prior is None or prior.value is None:
                reasons.append("MISSING_BASELINE")
            else:
                changes["absolute_change"] = point.value - prior.value
                if prior.value:
                    changes["relative_change"] = (
                        point.value - prior.value
                    ) / prior.value
                else:
                    reasons.append("PREVIOUS_ZERO")
                if point.ratio is not None and prior.ratio is not None:
                    changes["ratio_change"] = point.ratio - prior.ratio
        output.append(point.model_copy(update={**changes, "reasons": tuple(reasons)}))
    return tuple(output)
