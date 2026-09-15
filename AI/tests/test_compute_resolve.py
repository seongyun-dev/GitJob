"""C-to-B resolution never guesses across result streams or input generations."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from test_compute_api import PREFIX, REGISTRY, TOKEN
from test_job_cohort import criteria

from trend.archive import (
    ARCHIVE_TREND_ALGORITHM_VERSION,
    PeriodGranularity,
    archive_trend,
)
from trend.archive_v2 import (
    HISTORICAL_ARCHIVE_TREND_ALGORITHM_VERSION,
    archive_historical_trend,
)
from worker.api import compute_versions, create_compute_app
from worker.jobs import job_stream
from worker.store import digest
from worker.trend_streams import archive_trend_stream, weekly_activity_trend_stream

COHORT_ID = "c-" + "1" * 64
DEMAND_ID = "c-" + "2" * 64
TREND_ID = "c-" + "3" * 64


class ResolveStore:
    """Only exposes read methods so a resolve test cannot hide a DB write."""

    def __init__(self, *, pair=None, trend=None):
        self.pair = pair
        self.trend = trend
        self.pair_calls = []
        self.trend_calls = []

    def get_job_head_pair(self, stream):
        self.pair_calls.append(stream)
        return self.pair

    def get_head_snapshot(self, kind, owner, stream):
        self.trend_calls.append((kind, owner, stream))
        return self.trend


class IntakeRunner:
    job_set_sink = object()
    running = False
    last_report = None

    def __init__(self, result, *, selected_criteria=None):
        self.result = result
        self.selected_criteria = selected_criteria or criteria()
        self.public_reports = []

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def current_job_result(self, selected):
        return self.result

    def resolve_job_criteria(self, selected):
        return self.result

    def resolve_job_selector(self, selector):
        return (
            (selector.criteria_at(self.selected_criteria.as_of), self.result)
            if self.result
            else None
        )


def _client(
    store,
    *,
    runner=None,
    monkeypatch=None,
    tmp_path=None,
    raise_server_exceptions=True,
):
    intake_config = None
    if runner is not None:
        assert monkeypatch is not None and tmp_path is not None
        monkeypatch.setattr("worker.intake.configured_runner", lambda *_args: runner)
        intake_config = tmp_path / "intake.json"
    app = create_compute_app(
        store=store,
        token=TOKEN,
        registry=REGISTRY,
        intake_config=intake_config,
    )
    return TestClient(
        app,
        headers={"Authorization": f"Bearer {TOKEN}"},
        raise_server_exceptions=raise_server_exceptions,
    )


def test_non_intake_job_resolve_returns_one_completed_cohort_demand_pair():
    selected = criteria()
    versions = compute_versions("JOB_BATCH", REGISTRY)
    store = ResolveStore(
        pair={
            "event_id": "job-event-1",
            "cohort_snapshot_id": COHORT_ID,
            "demand_snapshot_id": DEMAND_ID,
        }
    )
    with _client(store) as client:
        response = client.post(
            PREFIX + "/job-cohorts/resolve", json=selected.model_dump(mode="json")
        )

    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "cohort_snapshot_id": COHORT_ID,
        "demand_snapshot_id": DEMAND_ID,
        "criteria": selected.model_dump(mode="json"),
        "compute_versions": versions,
    }
    assert store.pair_calls == [job_stream(selected, versions)]


def test_intake_job_resolve_uses_only_current_verified_receipt(monkeypatch, tmp_path):
    selected = criteria()
    store = ResolveStore(
        pair={
            "event_id": "stale-db-event",
            "cohort_snapshot_id": "c-" + "a" * 64,
            "demand_snapshot_id": "c-" + "b" * 64,
        }
    )
    runner = IntakeRunner(
        {
            "status": "COMPLETED",
            "results": [
                {"kind": "COHORT", "snapshot_id": COHORT_ID},
                {"kind": "DEMAND", "snapshot_id": DEMAND_ID},
            ],
        }
    )
    with _client(
        store, runner=runner, monkeypatch=monkeypatch, tmp_path=tmp_path
    ) as client:
        response = client.post(
            PREFIX + "/job-cohorts/resolve", json=selected.model_dump(mode="json")
        )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["cohort_snapshot_id"] == COHORT_ID
    assert response.json()["data"]["demand_snapshot_id"] == DEMAND_ID
    assert store.pair_calls == []


def test_intake_job_resolve_does_not_fall_back_before_first_valid_poll(
    monkeypatch, tmp_path
):
    store = ResolveStore(
        pair={
            "event_id": "stale-db-event",
            "cohort_snapshot_id": COHORT_ID,
            "demand_snapshot_id": DEMAND_ID,
        }
    )
    with _client(
        store,
        runner=IntakeRunner(None),
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    ) as client:
        response = client.post(
            PREFIX + "/job-cohorts/resolve", json=criteria().model_dump(mode="json")
        )

    assert response.status_code == 404
    assert response.json()["code"] == "COHORT_NOT_PREPARED"
    assert store.pair_calls == []


def test_intake_job_resolve_accepts_stable_role_and_user_filters_without_as_of(
    monkeypatch, tmp_path
):
    selected = criteria(as_of="2026-09-13T00:00:00Z")
    receipt = {
        "status": "COMPLETED",
        "results": [
            {"kind": "COHORT", "snapshot_id": COHORT_ID},
            {"kind": "DEMAND", "snapshot_id": DEMAND_ID},
        ],
    }
    store = ResolveStore(pair=None)
    runner = IntakeRunner(receipt, selected_criteria=selected)
    with _client(
        store, runner=runner, monkeypatch=monkeypatch, tmp_path=tmp_path
    ) as client:
        response = client.post(
            PREFIX + "/job-cohorts/resolve",
            json={
                "schema_version": "job-cohort-resolve-selector/v1",
                "target_role": "BACKEND",
            },
        )
        filtered = client.post(
            PREFIX + "/job-cohorts/resolve",
            json={
                "schema_version": "job-cohort-resolve-selector/v1",
                "target_role": "BACKEND",
                "regions": ["서울"],
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["criteria"] == selected.model_dump(mode="json")
    assert response.json()["data"]["cohort_snapshot_id"] == COHORT_ID
    assert response.json()["data"]["demand_snapshot_id"] == DEMAND_ID
    assert filtered.status_code == 200
    assert filtered.json()["data"]["criteria"]["regions"] == ["서울"]
    assert store.pair_calls == []


def test_http_only_job_resolve_does_not_guess_a_stable_selector_from_old_heads():
    store = ResolveStore(
        pair={
            "event_id": "old-event",
            "cohort_snapshot_id": COHORT_ID,
            "demand_snapshot_id": DEMAND_ID,
        }
    )
    with _client(store) as client:
        response = client.post(
            PREFIX + "/job-cohorts/resolve",
            json={
                "schema_version": "job-cohort-resolve-selector/v1",
                "target_role": "BACKEND",
            },
        )

    assert response.status_code == 404
    assert store.pair_calls == []


def test_intake_job_resolve_preserves_preparing_as_retryable_202(monkeypatch, tmp_path):
    selected = criteria(as_of="2026-09-13T00:00:00Z")
    runner = IntakeRunner(
        {"status": "PREPARING", "results": []}, selected_criteria=selected
    )
    with _client(
        ResolveStore(), runner=runner, monkeypatch=monkeypatch, tmp_path=tmp_path
    ) as client:
        response = client.post(
            PREFIX + "/job-cohorts/resolve",
            json={
                "schema_version": "job-cohort-resolve-selector/v1",
                "target_role": "BACKEND",
            },
        )

    assert response.status_code == 202
    assert response.headers["Retry-After"] == "2"
    assert response.json()["data"] == {
        "status": "PREPARING",
        "criteria": selected.model_dump(mode="json"),
        "compute_versions": compute_versions("JOB_BATCH", REGISTRY),
    }


def _trend_head(payload):
    return {
        "snapshot_id": TREND_ID,
        "event_id": "trend-event-1",
        "occurred_at": datetime(2026, 9, 14, tzinfo=UTC),
        "payload": payload,
    }


def test_weekly_trend_resolve_uses_weekly_stream_without_period_selector():
    payload = archive_trend(
        "python",
        (),
        REGISTRY,
        periods=("2026-09-07",),
        granularity=PeriodGranularity.WEEK,
        include_partial=False,
    ).model_dump(mode="json")
    store = ResolveStore(trend=_trend_head(payload))
    request = {
        "source": "WEEKLY_REPO_ACTIVITY",
        "tech_id": "python",
        "include_partial": False,
    }
    with _client(store) as client:
        response = client.post(PREFIX + "/trends/resolve", json=request)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["snapshot_id"] == TREND_ID
    assert response.json()["data"]["selector"] == request
    assert response.json()["data"]["periods"] == ["2026-09-07"]
    assert store.trend_calls == [
        (
            "TREND",
            None,
            weekly_activity_trend_stream(
                tech_id="python",
                registry_version=REGISTRY.registry_version,
                include_partial=False,
            ),
        )
    ]


def test_archive_sources_resolve_distinct_exact_streams():
    cases = (
        ("GH_ARCHIVE", "v1", ARCHIVE_TREND_ALGORITHM_VERSION),
        (
            "GH_ARCHIVE_HISTORICAL",
            "v2",
            HISTORICAL_ARCHIVE_TREND_ALGORITHM_VERSION,
        ),
    )
    observed = []
    for source, archive_version, algorithm in cases:
        builder = archive_trend if archive_version == "v1" else archive_historical_trend
        payload = builder(
            "react",
            (),
            REGISTRY,
            periods=("2026-08",),
            granularity=PeriodGranularity.MONTH,
            include_partial=True,
        ).model_dump(mode="json")
        store = ResolveStore(trend=_trend_head(payload))
        request = {
            "source": source,
            "tech_id": "react",
            "periods": ["2026-08"],
            "granularity": "MONTH",
            "include_partial": True,
        }
        with _client(store) as client:
            response = client.post(PREFIX + "/trends/resolve", json=request)
        assert response.status_code == 200, response.text
        assert response.json()["data"]["algorithm_version"] == algorithm
        observed.append(store.trend_calls[0][2])
        assert store.trend_calls[0][2] == archive_trend_stream(
            archive_version=archive_version,
            tech_id="react",
            periods=("2026-08",),
            granularity="MONTH",
            include_partial=True,
            registry_version=REGISTRY.registry_version,
            algorithm=algorithm,
        )
    assert observed[0] != observed[1]


def test_shared_archive_stream_helper_preserves_published_v1_and_v2_identity():
    common = {
        "tech_id": "react",
        "periods": ("2026-08",),
        "granularity": "MONTH",
        "include_partial": False,
        "registry": REGISTRY.registry_version,
    }
    assert archive_trend_stream(
        archive_version="v1",
        registry_version=common["registry"],
        algorithm=ARCHIVE_TREND_ALGORITHM_VERSION,
        **{key: value for key, value in common.items() if key != "registry"},
    ) == digest(
        {
            "source": "GH_ARCHIVE",
            **common,
            "algorithm": ARCHIVE_TREND_ALGORITHM_VERSION,
        }
    )
    assert archive_trend_stream(
        archive_version="v2",
        registry_version=common["registry"],
        algorithm=HISTORICAL_ARCHIVE_TREND_ALGORITHM_VERSION,
        **{key: value for key, value in common.items() if key != "registry"},
    ) == digest(
        {
            "source": "GH_ARCHIVE_HISTORICAL",
            **common,
            "algorithm": HISTORICAL_ARCHIVE_TREND_ALGORITHM_VERSION,
            "archive_version": "v2",
        }
    )


def test_trend_resolve_rejects_cross_source_selectors_and_unknown_tech():
    store = ResolveStore()
    invalid = (
        {
            "source": "WEEKLY_REPO_ACTIVITY",
            "tech_id": "python",
            "periods": ["2026-08"],
            "granularity": "MONTH",
        },
        {
            "source": "GH_ARCHIVE",
            "tech_id": "python",
            "periods": [],
            "granularity": "MONTH",
        },
        {
            "source": "GH_ARCHIVE_HISTORICAL",
            "tech_id": "python",
            "periods": ["2026-W36"],
            "granularity": "WEEK",
        },
        {"source": "WEEKLY_REPO_ACTIVITY", "tech_id": "not-in-registry"},
    )
    with _client(store) as client:
        responses = [
            client.post(PREFIX + "/trends/resolve", json=row) for row in invalid
        ]

    assert [response.status_code for response in responses] == [422, 422, 422, 422]
    assert store.trend_calls == []


def test_trend_resolve_returns_404_without_a_matching_head():
    store = ResolveStore(trend=None)
    with _client(store) as client:
        response = client.post(
            PREFIX + "/trends/resolve",
            json={
                "source": "WEEKLY_REPO_ACTIVITY",
                "tech_id": "python",
                "include_partial": False,
            },
        )

    assert response.status_code == 404
    assert response.json()["code"] == "TREND_NOT_PREPARED"


def test_trend_resolve_reports_corrupt_stored_payload_as_server_failure():
    store = ResolveStore(trend=_trend_head({"not": "a trend result"}))
    with _client(store, raise_server_exceptions=False) as client:
        response = client.post(
            PREFIX + "/trends/resolve",
            json={"source": "WEEKLY_REPO_ACTIVITY", "tech_id": "python"},
        )

    assert response.status_code == 500
    assert response.json()["code"] == "COMPUTE_FAILED"


def test_contracts_publish_the_trend_resolve_selector_schema():
    with _client(ResolveStore()) as client:
        response = client.get(PREFIX + "/contracts")

    assert response.status_code == 200
    schema = response.json()["data"]["TrendResolveSelector"]
    assert set(schema["properties"]["source"]["enum"]) == {
        "WEEKLY_REPO_ACTIVITY",
        "GH_ARCHIVE",
        "GH_ARCHIVE_HISTORICAL",
    }
    assert (
        response.json()["data"]["JobCohortResolveSelector"]["properties"][
            "schema_version"
        ]["const"]
        == "job-cohort-resolve-selector/v1"
    )
