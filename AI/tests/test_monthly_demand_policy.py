"""Historical posting demand must not become current matching inventory."""

from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_compute_api import PREFIX, event, snapshot_ref
from test_compute_api import (
    client as client,  # noqa: PLC0414 - pytest fixture re-export
)
from test_job_cohort import batch, criteria, posting
from test_job_input_union import output
from test_job_union_intake import completed, resolve
from test_job_union_intake import (
    runtime as runtime,  # noqa: PLC0414 - pytest fixture re-export
)
from test_recommendation_engine import make_analysis

from job.cohort import CohortCriteria, build_cohort
from job.demand import aggregate_demand
from job.input_union import build_input_union
from recommendation.engine import build_recommendations, simulate_what_if
from recommendation.evidence import consume_evidence
from registry.contracts import load_registry
from registry.mapper import RegistryMapper
from trend.job import job_trend
from worker.api import compute_versions
from worker.intake import _publish_job_trend_range
from worker.jobs import job_artifacts, job_stream
from worker.store import Ticket
from worker.trend_streams import job_trend_stream

REGISTRY = load_registry(
    Path(__file__).resolve().parents[1] / "registry/data/technology_registry_v1.json",
    repository_root=Path(__file__).resolve().parents[2],
)


def monthly_criteria(**changes):
    return criteria(
        **{
            "purpose": "MONTHLY_DEMAND",
            "as_of": "2026-09-01T00:00:00+09:00",
            "posted_from": "2026-08-01T00:00:00+09:00",
            "posted_to": "2026-09-01T00:00:00+09:00",
            **changes,
        }
    )


def august_posting(identifier="august", **changes):
    return posting(
        identifier,
        **{
            "posted_at": "2026-08-10T12:00:00+09:00",
            "collected_at": "2026-08-25T12:00:00+09:00",
            "deadline": "2026-09-05T00:00:00+09:00",
            **changes,
        },
    )


def test_later_deadline_passage_changes_active_inventory_not_monthly_demand():
    inputs = batch(
        august_posting("short"),
        august_posting("long", deadline="2026-10-01T00:00:00+09:00"),
    )
    early, late = "2026-09-01T00:00:00+09:00", "2026-09-10T00:00:00+09:00"
    active = [build_cohort(inputs, criteria(as_of=stamp)) for stamp in (early, late)]
    monthly = [
        aggregate_demand(build_cohort(inputs, monthly_criteria(as_of=stamp)))
        for stamp in (early, late)
    ]
    assert [len(cohort.jobs) for cohort in active] == [2, 1]
    assert [demand.denominator for demand in monthly] == [2, 2]
    assert [demand.technologies[0].total_count for demand in monthly] == [2, 2]
    assert all(not demand.excluded_count for demand in monthly)


def test_closed_and_month_midpoint_deadline_are_still_observed_monthly_demand():
    closed = august_posting(
        posting_status="CLOSED", deadline="2026-08-20T00:00:00+09:00"
    )
    active = build_cohort(batch(closed), criteria())
    monthly = build_cohort(batch(closed), monthly_criteria())
    assert active.jobs == ()
    assert {reason for item in active.exclusions for reason in item.reasons} == {
        "POSTING_CLOSED",
        "DEADLINE_PASSED",
    }
    assert [job.job_id for job in monthly.jobs] == ["august"]
    assert monthly.jobs[0].deadline == closed.deadline
    assert monthly.jobs[0].content_hash == closed.content_hash
    assert monthly.jobs[0].posting_status == "CLOSED"


def test_monthly_policy_keeps_quality_and_collection_cutoff_checks():
    inputs = batch(
        august_posting("unknown", posting_status="UNKNOWN"),
        august_posting("future", collected_at="2026-09-10T00:00:00+09:00"),
        august_posting("undated", posted_at=None),
        august_posting("other-month", posted_at="2026-07-31T23:59:59+09:00"),
    )
    result = build_cohort(inputs, monthly_criteria())
    assert result.jobs == ()
    assert {row.source_record_id: row.reasons for row in result.exclusions} == {
        "future": ("COLLECTED_AFTER_AS_OF",),
        "other-month": ("OUTSIDE_POSTED_PERIOD",),
        "undated": ("POSTED_AT_UNKNOWN",),
        "unknown": ("POSTING_STATUS_UNKNOWN",),
    }


def test_month_boundary_is_seoul_midnight_and_end_is_exclusive():
    inputs = batch(
        august_posting("start", posted_at="2026-07-31T15:00:00Z"),
        august_posting("before", posted_at="2026-07-31T14:59:59Z"),
        august_posting("end", posted_at="2026-08-31T15:00:00Z"),
    )
    result = build_cohort(inputs, monthly_criteria())
    assert [job.job_id for job in result.jobs] == ["start"]


@pytest.mark.parametrize(
    "change",
    [
        {"posted_from": None},
        {"posted_to": None},
        {"posted_from": "2026-08-02T00:00:00+09:00"},
        {"posted_to": "2026-08-31T00:00:00+09:00"},
        {"as_of": "2026-08-31T23:59:59+09:00"},
    ],
)
def test_monthly_criteria_require_a_complete_calendar_month(change):
    with pytest.raises(ValidationError, match="MONTH_|FULL_MONTH"):
        monthly_criteria(**change)


def test_default_active_payload_keeps_legacy_hashes_and_explicit_default_identity():
    implicit = criteria()
    explicit = criteria(purpose="ACTIVE_MATCHING")
    assert implicit.purpose == "ACTIVE_MATCHING"
    assert implicit.model_dump(mode="json") == explicit.model_dump(mode="json")
    assert "purpose" not in implicit.model_dump(mode="json")
    assert job_stream(implicit, {}) == job_stream(explicit, {})
    historical = monthly_criteria()
    assert historical.model_dump(mode="json")["purpose"] == "MONTHLY_DEMAND"
    assert (
        CohortCriteria.model_validate_json(historical.model_dump_json()) == historical
    )


@pytest.mark.parametrize("consumer", ["recommendation", "what_if"])
def test_historical_population_is_rejected_by_matching_consumers(consumer):
    cohort = build_cohort(batch(august_posting()), monthly_criteria())
    analysis = make_analysis()
    with pytest.raises(ValueError, match="ACTIVE_MATCHING_COHORT_REQUIRED"):
        if consumer == "recommendation":
            build_recommendations(
                cohort, analysis, user_id="user-1", analysis_id="analysis-1"
            )
        else:
            held = consume_evidence(
                analysis,
                user_id="user-1",
                analysis_id="analysis-1",
                tech_ids=("java", "docker"),
            )
            simulate_what_if(cohort, held, "docker")


def test_trend_rejects_legacy_active_population_instead_of_relabeling_it():
    selected = criteria(
        posted_from="2026-08-01T00:00:00+09:00",
        posted_to="2026-09-01T00:00:00+09:00",
    )
    demand = aggregate_demand(build_cohort(batch(august_posting()), selected))
    trend = job_trend("java", (demand,), REGISTRY, periods=("2026-08",))
    assert trend.status == "FAILED"
    assert trend.reasons == ("MONTHLY_DEMAND_COHORT_REQUIRED",)


def test_monthly_trend_carries_population_and_does_not_fill_missing_months():
    demand = aggregate_demand(build_cohort(batch(august_posting()), monthly_criteria()))
    trend = job_trend("java", (demand,), REGISTRY, periods=("2026-07", "2026-08"))
    assert trend.status == "INSUFFICIENT_DATA"
    assert [point.value for point in trend.points] == [None, 1]
    assert [point.denominator for point in trend.points] == [None, 1]
    assert trend.filters["purpose"] == "MONTHLY_DEMAND"
    assert trend.filters["posting_status_policy"] == "INCLUDE_CLOSED"
    assert trend.points[1].as_of == demand.criteria.as_of.isoformat()


def test_monthly_intake_publishes_resolvable_trends_for_every_active_technology():
    demands = []
    for month in (7, 8):
        selected = monthly_criteria(
            posted_from=f"2026-{month:02d}-01T00:00:00+09:00",
            posted_to=f"2026-{month + 1:02d}-01T00:00:00+09:00",
        )
        value = august_posting(
            f"java-{month}",
            posted_at=f"2026-{month:02d}-10T12:00:00+09:00",
            required=("Java",),
        )
        demands.append(aggregate_demand(build_cohort(batch(value), selected)))

    class Store:
        lease_seconds = 120

        def __init__(self):
            self.artifacts = []

        def claim(self, **kwargs):
            return Ticket(
                event_id=kwargs["event_id"],
                kind=kwargs["kind"],
                owner=kwargs["owner"],
                occurred_at=kwargs["occurred_at"],
                status="RUNNING",
                token="owned-token",
                attempt=1,
                results=[],
            )

        def complete(self, _ticket, artifacts):
            self.artifacts = artifacts
            return []

        def renew(self, _ticket):
            return True

        def fail(self, *_args):
            raise AssertionError("successful publication must not fail the ticket")

    store = Store()
    refs = tuple((f"c-demand-{index}", demand) for index, demand in enumerate(demands))

    assert _publish_job_trend_range(
        refs, ("2026-07", "2026-08"), store=store, registry=REGISTRY
    )
    assert len(store.artifacts) == sum(
        technology.status.value == "ACTIVE" for technology in REGISTRY.technologies
    )
    java = next(
        artifact
        for artifact in store.artifacts
        if artifact.payload["tech_id"] == "java"
    )
    assert java.payload["status"] == "READY"
    assert [point["value"] for point in java.payload["points"]] == [1, 1]
    assert java.stream == job_trend_stream(
        tech_id="java",
        periods=("2026-07", "2026-08"),
        target_role="BACKEND",
        sources=(),
        regions=(),
        career_levels=(),
        min_jobs=1,
        registry_version=REGISTRY.registry_version,
        versions=compute_versions("TREND", REGISTRY),
    )


def test_completion_artifacts_use_disjoint_active_and_monthly_streams():
    inputs = batch(august_posting())
    selected = monthly_criteria()
    active = criteria(
        as_of=selected.as_of,
        posted_from=selected.posted_from,
        posted_to=selected.posted_to,
    )
    mapper = RegistryMapper(REGISTRY)
    current = job_artifacts(inputs, active, mapper, {})
    monthly = job_artifacts(inputs, selected, mapper, {})
    assert [artifact.kind for artifact in monthly] == ["COHORT", "DEMAND"]
    assert current[0].stream != monthly[0].stream
    assert monthly[0].stream == monthly[1].stream
    assert monthly[1].payload["criteria"]["purpose"] == "MONTHLY_DEMAND"


def test_december_to_january_and_leap_february_are_complete_months():
    for start, end in (("2026-12-01", "2027-01-01"), ("2024-02-01", "2024-03-01")):
        result = monthly_criteria(
            posted_from=start + "T00:00:00+09:00",
            posted_to=end + "T00:00:00+09:00",
            as_of=end + "T00:00:00+09:00",
        )
        assert result.posted_to == datetime.fromisoformat(end + "T00:00:00+09:00")


def test_monthly_completed_input_database_trend_and_matching_boundary(client):
    demands = []
    for month in (7, 8):
        selected = monthly_criteria(
            posted_from=f"2026-{month:02}-01T00:00:00+09:00",
            posted_to=f"2026-{month + 1:02}-01T00:00:00+09:00",
            as_of="2026-09-10T00:00:00+09:00",
        )
        inputs = batch(
            august_posting(
                f"closed-{month}",
                posted_at=f"2026-{month:02}-10T12:00:00+09:00",
                posting_status="CLOSED",
            )
        )
        request = event(
            batch=inputs.model_dump(mode="json"),
            criteria=selected.model_dump(mode="json"),
        )
        saved = client.post(PREFIX + "/job-batches/completed", json=request)
        cohort_id = snapshot_ref(saved, "COHORT")
        demand_id = snapshot_ref(saved, "DEMAND")
        demands.append(demand_id)
        assert (
            client.post(PREFIX + "/job-batches/completed", json=request).json()
            == saved.json()
        )
        payload = client.get(PREFIX + f"/snapshots/{demand_id}").json()["data"][
            "payload"
        ]
        assert payload["denominator"] == 1
        assert payload["criteria"]["purpose"] == "MONTHLY_DEMAND"
        matching = client.post(
            PREFIX + "/analyses/completed",
            json=event(
                user_id="user-1",
                analysis_id="analysis-1",
                cohort_snapshot_id=cohort_id,
                evidence=make_analysis().model_dump(mode="json"),
            ),
        )
        assert matching.status_code == 422
    trend_id = snapshot_ref(
        client.post(
            PREFIX + "/trends/completed",
            json=event(
                tech_id="java",
                source="JOB",
                periods=["2026-07", "2026-08"],
                demand_snapshot_ids=demands,
            ),
        ),
        "TREND",
    )
    trend = client.get(PREFIX + f"/snapshots/{trend_id}").json()["data"]["payload"]
    assert trend["status"] == "READY"
    assert [point["value"] for point in trend["points"]] == [1, 1]
    assert trend["filters"]["purpose"] == "MONTHLY_DEMAND"


def test_active_demand_is_not_reused_as_monthly_trend_over_http(client):
    selected = criteria(
        posted_from="2026-08-01T00:00:00+09:00",
        posted_to="2026-09-01T00:00:00+09:00",
    )
    saved = client.post(
        PREFIX + "/job-batches/completed",
        json=event(
            batch=batch(august_posting()).model_dump(mode="json"),
            criteria=selected.model_dump(mode="json"),
        ),
    )
    demand_id = snapshot_ref(saved, "DEMAND")
    result = client.post(
        PREFIX + "/trends/completed",
        json=event(
            tech_id="java",
            source="JOB",
            periods=["2026-08"],
            demand_snapshot_ids=[demand_id],
        ),
    )
    trend_id = snapshot_ref(result, "TREND")
    payload = client.get(PREFIX + f"/snapshots/{trend_id}").json()["data"]["payload"]
    assert payload["status"] == "FAILED"
    assert payload["reasons"] == ["MONTHLY_DEMAND_COHORT_REQUIRED"]


def test_job_trend_policy_version_is_bound_to_completed_event(client, monkeypatch):
    saved = client.post(
        PREFIX + "/job-batches/completed",
        json=event(
            batch=batch(august_posting()).model_dump(mode="json"),
            criteria=monthly_criteria().model_dump(mode="json"),
        ),
    )
    request = event(
        tech_id="java",
        source="JOB",
        periods=["2026-08"],
        demand_snapshot_ids=[snapshot_ref(saved, "DEMAND")],
    )
    trend_id = snapshot_ref(
        client.post(PREFIX + "/trends/completed", json=request), "TREND"
    )
    monkeypatch.setattr(
        "trend.job.JOB_TREND_POLICY_VERSION", "c-job-monthly-demand/future"
    )
    replay = client.post(PREFIX + "/trends/completed", json=request)
    assert replay.status_code == 409
    assert replay.json()["code"] == "IDEMPOTENCY_CONFLICT"
    original = client.get(PREFIX + f"/snapshots/{trend_id}").json()["data"]["payload"]
    assert original["algorithm_version"] == "c-job-monthly-demand/v1"


def test_latest_closed_observation_is_retained_only_in_historical_population():
    old = output(august_posting(), run="old")
    latest = output(
        august_posting(
            posting_status="CLOSED", collected_at="2026-09-06T00:00:00+09:00"
        ),
        run="latest",
    )
    selected = monthly_criteria(as_of="2026-09-10T00:00:00+09:00")
    mapper = RegistryMapper(REGISTRY)
    historical = build_input_union((old, latest), selected, mapper)
    active = build_input_union((old, latest), criteria(as_of=selected.as_of), mapper)
    assert active.jobs == ()
    assert len(historical.jobs) == 1
    assert historical.jobs[0].posting_status == "CLOSED"
    assert historical.jobs[0].collected_at == latest.occurred_at
    assert historical.input_union.superseded_record_count == 1


def test_historical_population_does_not_restore_older_body_after_quality_failure():
    old = output(august_posting(), run="old")
    latest = output(
        august_posting(
            posting_status="CLOSED",
            body_status="MISSING",
            description_text=None,
            technology_mentions=(),
            collected_at="2026-09-06T00:00:00+09:00",
        ),
        run="latest",
    )
    cohort = build_input_union(
        (old, latest),
        monthly_criteria(as_of="2026-09-10T00:00:00+09:00"),
        RegistryMapper(REGISTRY),
    )
    assert cohort.jobs == ()
    assert cohort.review_count == 1
    assert "BODY_UNAVAILABLE" in cohort.exclusions[0].reasons


def test_automatic_intake_keeps_monthly_and_active_results_separate(runtime):
    root, _, open_runtime = runtime
    completed(
        root,
        "SARAMIN",
        "closed",
        at="2026-08-25T12:00:00+09:00",
        posted_at="2026-08-10T12:00:00+09:00",
        deadline="2026-08-20T00:00:00+09:00",
        posting_status="CLOSED",
    )
    monthly = monthly_criteria()
    active = criteria(
        as_of=monthly.as_of,
        posted_from=monthly.posted_from,
        posted_to=monthly.posted_to,
    )
    with open_runtime(monthly)[0] as value:
        assert value.app.state.intake_runner.poll_once()["completed"] == 1
        monthly_id, cohort = resolve(value, monthly)
        assert cohort["criteria"]["purpose"] == "MONTHLY_DEMAND"
        assert len(cohort["jobs"]) == 1
        assert cohort["jobs"][0]["posting_status"] == "CLOSED"
    with open_runtime(active)[0] as value:
        value.app.state.intake_runner.poll_once()
        active_id, cohort = resolve(value, active)
        assert cohort["jobs"] == []
        assert active_id != monthly_id


def test_automatic_intake_materializes_the_job_trend_ranges_used_by_the_ui(runtime):
    root, _, open_runtime = runtime
    completed(
        root,
        "SARAMIN",
        "august-java-trend",
        at="2026-09-15T22:30:04Z",
        posted_at="2026-08-10T12:00:00+09:00",
        posting_status="CLOSED",
        required=("Java",),
    )
    active = criteria(as_of="2026-09-16T00:00:00Z")
    periods = [f"2026-{month:02d}" for month in range(3, 9)]

    with open_runtime(active)[0] as client:
        runner = client.app.state.intake_runner
        report = runner.poll_once()
        assert report["failed"] == 0
        resolved = client.post(
            PREFIX + "/trends/resolve",
            json={
                "source": "JOB",
                "tech_id": "java",
                "periods": periods,
                "granularity": "MONTH",
                "target_role": "BACKEND",
                "min_jobs": 1,
            },
        )
        assert resolved.status_code == 200, resolved.text
        trend_id = resolved.json()["data"]["snapshot_id"]
        payload = client.get(PREFIX + f"/snapshots/{trend_id}").json()["data"][
            "payload"
        ]
        assert payload["source"] == "JOB"
        assert payload["points"][-1]["period"] == "2026-08"
        assert payload["points"][-1]["value"] == 1
