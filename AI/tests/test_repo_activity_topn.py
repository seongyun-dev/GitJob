import pytest
from repo_activity_topn import (
    DEFAULT_TOP_N,
    HISTORICAL_CUTOFF,
    HISTORICAL_START,
    coverage_rows_from_ranked,
    parse_top_n,
    parse_utc_hour,
    rank_activity_rows,
    SUPPORTED_HISTORICAL_CUTOFF,
    SUPPORTED_HISTORICAL_START,
    validate_period,
)


def test_small_fixture_orders_activity_and_ties_deterministically() -> None:
    ranked = rank_activity_rows(
        [
            {"repo_id": 30, "repo_name": "repo-c", "activity_count": 2},
            {"repo_id": 10, "repo_name": "repo-a", "activity_count": 5},
            {"repo_id": 20, "repo_name": "repo-b", "activity_count": 5},
        ]
    )

    assert [(row["repo_id"], row["activity_count"], row["rank"]) for row in ranked] == [
        (10, 5, 1),
        (20, 5, 2),
        (30, 2, 3),
    ]


def test_small_fixture_coverage_uses_valid_and_total_denominators() -> None:
    ranked = rank_activity_rows(
        [
            {"repo_id": 1, "repo_name": "repo-a", "activity_count": 5},
            {"repo_id": 2, "repo_name": "repo-b", "activity_count": 3},
            {"repo_id": 3, "repo_name": "repo-c", "activity_count": 2},
        ]
    )

    coverage = coverage_rows_from_ranked(
        ranked,
        [1, 2, 10],
        total_input_events=12,
        valid_repo_event_count=10,
    )

    assert [row["event_count"] for row in coverage] == [5, 8, 10]
    assert [row["selected_repo_count"] for row in coverage] == [1, 2, 3]
    assert coverage[0]["coverage_valid"] == pytest.approx(0.5)
    assert coverage[0]["coverage_total"] == pytest.approx(5 / 12)
    assert coverage[1]["coverage_delta_valid"] == pytest.approx(0.3)
    assert coverage[2]["coverage_delta_valid"] == pytest.approx(0.2)


def test_top_n_larger_than_unique_repo_count_is_supported() -> None:
    ranked = rank_activity_rows(
        [{"repo_id": 1, "repo_name": "repo-a", "activity_count": 1}]
    )

    coverage = coverage_rows_from_ranked(
        ranked,
        [10000],
        total_input_events=1,
        valid_repo_event_count=1,
    )

    assert coverage[0]["selected_repo_count"] == 1
    assert coverage[0]["coverage_valid"] == 1.0


def test_empty_fixture_has_zero_coverage_without_division_error() -> None:
    coverage = coverage_rows_from_ranked(
        [],
        [100, 500],
        total_input_events=0,
        valid_repo_event_count=0,
    )

    assert coverage[0]["event_count"] == 0
    assert coverage[0]["coverage_valid"] == 0.0
    assert coverage[1]["coverage_total"] == 0.0


def test_parse_top_n_sorts_and_rejects_invalid_values() -> None:
    assert parse_top_n("10000, 100, 500") == (100, 500, 10000)
    assert parse_top_n(",".join(str(value) for value in DEFAULT_TOP_N)) == DEFAULT_TOP_N
    for invalid in ("0", "-1", "100,100", "abc", "100,"):
        with pytest.raises(ValueError):
            parse_top_n(invalid)


def test_period_is_utc_start_inclusive_and_cutoff_exclusive() -> None:
    validate_period(HISTORICAL_START, HISTORICAL_CUTOFF)
    assert parse_utc_hour(HISTORICAL_START).isoformat() == "2026-08-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="historical_cutoff"):
        validate_period(HISTORICAL_START, "2026-09-01T01:00:00Z")
    with pytest.raises(ValueError, match="precedes historical_start"):
        validate_period("2026-02-28T23:00:00Z", HISTORICAL_CUTOFF)


def test_six_month_historical_window_is_supported() -> None:
    validate_period(SUPPORTED_HISTORICAL_START, SUPPORTED_HISTORICAL_CUTOFF)
    assert parse_utc_hour(SUPPORTED_HISTORICAL_START).isoformat() == "2026-03-01T00:00:00+00:00"
