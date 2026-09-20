"""Shadow comparisons are bounded and preserve category/rank semantics."""

from threading import Event

from test_job_cohort import batch, criteria, posting

from job.cohort import build_cohort
from job.demand import aggregate_demand
from worker.projection_shadow import ProjectionShadow, compare_demands


def test_compare_demands_reports_job_and_aggregate_fields(monkeypatch):
    monkeypatch.setenv("C_REGISTRY_BACKEND", "file")
    demand = aggregate_demand(build_cohort(batch(posting("one")), criteria()))
    assert compare_demands(
        demand,
        demand,
        legacy_job_ids=("one",),
        projected_job_ids=("two",),
    ) == ("job_ids",)

    assert compare_demands(
        demand,
        demand,
        legacy_job_ids=("one",),
        projected_job_ids=("two", "three"),
    ) == ("job_ids", "job_count")


def test_shadow_executor_records_completed_comparison():
    completed = Event()
    shadow = ProjectionShadow(sample_rate=1, queue_size=1)

    assert shadow.submit(criteria(), lambda: completed.set() or ())
    assert completed.wait(2)
    shadow.close()

    metrics = shadow.metrics()
    assert metrics["projection_shadow_submitted_total"] == 1
    assert metrics["projection_shadow_compared_total"] == 1
    assert metrics["projection_shadow_mismatch_total"] == 0


def test_shadow_executor_records_mismatch_reason_counters():
    shadow = ProjectionShadow(sample_rate=1, queue_size=1)

    assert shadow.submit(
        criteria(),
        lambda: (
            "job_ids",
            "job_count",
            "technology_ids",
            "technology_ranks",
            "denominator",
        ),
    )
    shadow.close()

    metrics = shadow.metrics()
    assert metrics["projection_shadow_mismatch_total"] == 1
    assert metrics["projection_shadow_selected_id_mismatch_total"] == 1
    assert metrics["projection_shadow_selected_count_mismatch_total"] == 1
    assert metrics["projection_shadow_technology_id_mismatch_total"] == 1
    assert metrics["projection_shadow_technology_rank_mismatch_total"] == 1
    assert metrics["projection_shadow_aggregate_mismatch_total"] == 1
