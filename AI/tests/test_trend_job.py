from datetime import datetime
from pathlib import Path

import pytest

from job.demand import DemandSnapshot
from registry.contracts import TechnologyRegistry
from trend.job import job_trend


@pytest.fixture
def registry():
    return TechnologyRegistry.model_validate_json(
        Path("registry/data/technology_registry_v1.json").read_text(encoding="utf-8")
    )


def snapshot(month, count=1, denominator=2, **overrides):
    payload = {
        "cohort_id": f"cohort-{month}",
        "status": "READY" if denominator else "EMPTY",
        "criteria": {
            "target_role": "BACKEND",
            "purpose": "MONTHLY_DEMAND",
            "as_of": "2026-04-01T00:00:00+09:00",
            "posted_from": f"2026-{month:02}-01T00:00:00+09:00",
            "posted_to": f"2026-{month + 1:02}-01T00:00:00+09:00",
            "sources": ("WORKNET",),
        },
        "denominator": denominator,
        "input_count": denominator,
        "duplicate_count": 0,
        "excluded_count": 0,
        "review_count": 0,
        "dataset_snapshot_id": f"dataset-{month}",
        "pipeline_run_id": f"run-{month}",
        "collector_version": "collector-v1",
        "registry_version": "registry-20260901.1",
        "parser_version": "parser-v1",
        "quality_version": "quality-v1",
        "technologies": (),
    }
    if count and denominator:
        payload["technologies"] = (
            {
                "tech_id": "java",
                "required_count": count,
                "preferred_count": count,
                "general_count": 0,
                "total_count": count,
                "required_ratio": count / denominator,
                "preferred_ratio": count / denominator,
                "general_ratio": 0.0,
                "total_ratio": count / denominator,
                "rank": 1,
            },
        )
    payload.update(overrides)
    return DemandSnapshot.model_validate(payload)


def test_overlapping_required_preferred_uses_distinct_total_and_denominator(registry):
    result = job_trend(
        "java",
        (snapshot(1), snapshot(2, 2, 4)),
        registry,
        periods=("2026-01", "2026-02"),
    )
    assert result.status == "READY"
    assert [p.value for p in result.points] == [1, 2]
    assert [p.denominator for p in result.points] == [2, 4]
    assert result.points[1].ratio == 0.5
    assert result.points[1].ratio_change == 0
    assert result.points[1].input_run_id == "run-2"


def test_missing_month_and_zero_prior_are_distinct(registry):
    result = job_trend(
        "java",
        (snapshot(1, 0), snapshot(2)),
        registry,
        periods=("2026-01", "2026-02", "2026-03"),
    )
    assert [p.value for p in result.points] == [0, 1, None]
    assert result.status == "INSUFFICIENT_DATA"
    assert result.points[1].absolute_change == 1
    assert result.points[1].relative_change is None
    assert "PREVIOUS_ZERO" in result.points[1].reasons


def test_unknown_registry_tech_not_false_zero(registry):
    assert (
        job_trend("imaginary", (snapshot(1),), registry, periods=("2026-01",)).status
        == "NOT_SUPPORTED"
    )


def test_duplicate_month_failed(registry):
    result = job_trend(
        "java", (snapshot(1), snapshot(1)), registry, periods=("2026-01",)
    )
    assert result.status == "FAILED"
    assert result.reasons == ("DUPLICATE_MONTH",)


@pytest.mark.parametrize("change", ["filters", "version", "partial", "as_of"])
def test_noncomparable_or_incomplete_month_rejected(registry, change):
    second = snapshot(2)
    if change == "filters":
        second = second.model_copy(
            update={
                "criteria": second.criteria.model_copy(update={"regions": ("서울",)})
            }
        )
    elif change == "version":
        second = second.model_copy(update={"parser_version": "other"})
    else:
        field = "posted_from" if change == "partial" else "as_of"
        second = second.model_copy(
            update={
                "criteria": second.criteria.model_copy(
                    update={field: datetime.fromisoformat("2026-02-10T00:00:00+09:00")}
                )
            }
        )
    result = job_trend(
        "java", (snapshot(1), second), registry, periods=("2026-01", "2026-02")
    )
    assert result.status == "FAILED"


def test_empty_denominator_is_insufficient_not_zero(registry):
    result = job_trend("java", (snapshot(1, 0, 0),), registry, periods=("2026-01",))
    assert result.status == "INSUFFICIENT_DATA"
    assert result.points[0].denominator == 0
    assert result.points[0].value is None
    assert result.points[0].ratio is None


def test_invalid_numerator_failed(registry):
    invalid = snapshot(1).model_copy(update={"denominator": 0})
    assert (
        job_trend("java", (invalid,), registry, periods=("2026-01",)).status == "FAILED"
    )
