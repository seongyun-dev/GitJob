"""Spark-free tests for the Weekly 7-day completeness verifier (-264).

Every decision the verifier makes about an hour lives in pure helpers, so the
cases below are the contract.  The Spark path only supplies the two counts.

The case that matters most is `test_partial_hour_with_heavy_duplication_fails`:
that shape -- raw rows far above the source count while distinct identities sit
far below it -- is what 2026-09 production actually looked like, and it is the
shape the presence-only coverage gate in `repo_activity_weekly` reports as
fully covered.
"""

import json

import pytest
from jobs.repo_activity_weekly import DEDUP_KEYS
from jobs.weekly_activity_verify import (
    HOUR_COMPLETE,
    HOUR_MISSING,
    HOUR_OVERFULL,
    HOUR_PARTIAL,
    HOUR_UNKNOWN,
    SCHEMA_VERSION,
    ExpectedCountsUnavailable,
    build_verification,
    classify_hour,
    expected_counts_from_publish_checkpoint,
    merge_expected_counts,
    normalize_expected_counts,
    summarize_reports,
)

DAY_START = "2026-09-07T00:00:00Z"
DAY_END = "2026-09-08T00:00:00Z"
WEEK_START = "2026-09-07T00:00:00Z"
WEEK_END = "2026-09-14T00:00:00Z"


def hour_keys(day: str) -> list[str]:
    return [f"{day}T{hour:02d}:00:00Z" for hour in range(24)]


def complete_day(day: str = "2026-09-07", events: int = 1000):
    """Expected and observed maps for one fully-landed day."""

    expected = {hour: events for hour in hour_keys(day)}
    observed = {
        hour: {"raw_row_count": events, "deduplicated_event_count": events}
        for hour in hour_keys(day)
    }
    return expected, observed


def verify(expected, observed, *, start=DAY_START, end=DAY_END):
    return build_verification(
        period_start=start,
        period_end=end,
        input_uri="hdfs:///gitjob/parquet/stream/github.events",
        expected_counts=expected,
        observed=observed,
    )


# 1. every hour complete


def test_full_period_passes():
    expected, observed = complete_day()
    report = verify(expected, observed)

    assert report["result"] == "PASS"
    assert report["schema_version"] == SCHEMA_VERSION
    assert report["dedup_keys"] == list(DEDUP_KEYS)
    summary = report["summary"]
    assert summary["expected_hour_count"] == 24
    assert summary["classification_counts"][HOUR_COMPLETE] == 24
    assert summary["blocking_hour_count"] == 0
    assert summary["expected_event_total"] == summary["deduplicated_event_total"]
    assert summary["shortfall_event_total"] == 0
    assert summary["totals_match"] is True


def test_seven_day_period_expects_168_hours():
    expected = {}
    observed = {}
    for day in range(7, 14):
        day_expected, day_observed = complete_day(f"2026-09-{day:02d}")
        expected.update(day_expected)
        observed.update(day_observed)

    report = verify(expected, observed, start=WEEK_START, end=WEEK_END)

    assert report["summary"]["expected_hour_count"] == 168
    assert report["result"] == "PASS"


# 2. the hour is not in the archive at all


def test_absent_hour_fails_as_missing():
    expected, observed = complete_day()
    del observed["2026-09-07T05:00:00Z"]

    report = verify(expected, observed)

    assert report["result"] == "FAIL"
    summary = report["summary"]
    assert summary["classification_counts"][HOUR_MISSING] == 1
    assert summary["blocking_hours"] == ["2026-09-07T05:00:00Z"]
    assert summary["shortfall_event_total"] == 1000


# 3. the hour is present but short


def test_partial_hour_fails():
    expected, observed = complete_day()
    observed["2026-09-07T05:00:00Z"] = {
        "raw_row_count": 400,
        "deduplicated_event_count": 400,
    }

    report = verify(expected, observed)

    assert report["result"] == "FAIL"
    assert report["summary"]["classification_counts"][HOUR_PARTIAL] == 1
    hour = next(h for h in report["hours"] if h["hour_key"] == "2026-09-07T05:00:00Z")
    assert hour["hour_present"] is True
    assert hour["coverage_ratio"] == 0.4


# 4. the 2026-09 production shape: a short prefix re-sent many times


def test_partial_hour_with_heavy_duplication_fails():
    """raw >> expected, dedup < expected.  Present, and nowhere near complete.

    `2026-09-04T00` on 2026-09-17: source 45,663 events, 108,384 rows in HDFS,
    9,032 distinct -- the same 19.8% prefix written 12 times.  The presence-only
    gate saw a populated hour.
    """

    expected, observed = complete_day()
    observed["2026-09-07T05:00:00Z"] = {
        "raw_row_count": 12_000,
        "deduplicated_event_count": 400,
    }

    report = verify(expected, observed)

    assert report["result"] == "FAIL"
    hour = next(h for h in report["hours"] if h["hour_key"] == "2026-09-07T05:00:00Z")
    assert hour["classification"] == HOUR_PARTIAL
    assert hour["hour_present"] is True
    assert hour["duplicate_count"] == 11_600
    assert hour["coverage_ratio"] == 0.4
    assert report["summary"]["duplicate_row_total"] == 11_600


# 5. duplicates alone are reported, not failed


def test_duplicates_with_full_coverage_pass():
    expected, observed = complete_day()
    observed["2026-09-07T05:00:00Z"] = {
        "raw_row_count": 12_000,
        "deduplicated_event_count": 1000,
    }

    report = verify(expected, observed)

    assert report["result"] == "PASS"
    assert report["summary"]["classification_counts"][HOUR_COMPLETE] == 24
    assert report["summary"]["duplicate_row_total"] == 11_000


# 6. more distinct identities than the source holds


def test_more_distinct_events_than_source_fails():
    expected, observed = complete_day()
    observed["2026-09-07T05:00:00Z"] = {
        "raw_row_count": 1500,
        "deduplicated_event_count": 1500,
    }

    report = verify(expected, observed)

    assert report["result"] == "FAIL"
    assert report["summary"]["classification_counts"][HOUR_OVERFULL] == 1


# 7. no expected count for an hour


def test_hour_without_expected_count_is_unknown_and_fails():
    expected, observed = complete_day()
    del expected["2026-09-07T05:00:00Z"]

    report = verify(expected, observed)

    assert report["result"] == "FAIL"
    summary = report["summary"]
    assert summary["classification_counts"][HOUR_UNKNOWN] == 1
    assert summary["expected_event_total"] is None
    assert summary["shortfall_event_total"] is None
    assert summary["totals_match"] is False


def test_no_expected_counts_at_all_is_refused():
    with pytest.raises(ExpectedCountsUnavailable):
        merge_expected_counts(None, {})


# 8. period boundaries


def test_period_start_after_end_is_refused():
    expected, observed = complete_day()
    with pytest.raises(ValueError):
        verify(expected, observed, start=DAY_END, end=DAY_START)


def test_period_hours_drive_the_report_not_the_observations():
    """An hour outside the period never reaches the report."""

    expected, observed = complete_day()
    expected["2026-09-08T00:00:00Z"] = 1000
    observed["2026-09-08T00:00:00Z"] = {
        "raw_row_count": 1000,
        "deduplicated_event_count": 1000,
    }

    report = verify(expected, observed)

    assert report["summary"]["expected_hour_count"] == 24
    assert all(h["hour_key"].startswith("2026-09-07") for h in report["hours"])


# 9. a foreign source is filtered before counting, so it simply never appears


def test_observations_for_unexpected_hours_are_ignored():
    expected, observed = complete_day()
    observed["2026-09-06T23:00:00Z"] = {
        "raw_row_count": 999_999,
        "deduplicated_event_count": 999_999,
    }

    report = verify(expected, observed)

    assert report["result"] == "PASS"
    assert report["summary"]["raw_row_total"] == 24_000


def test_report_records_the_source_it_counted():
    expected, observed = complete_day()
    assert verify(expected, observed)["source"] == "gharchive"


# 10. malformed hour keys are refused rather than silently skipped


def test_malformed_expected_hour_key_is_refused():
    with pytest.raises(ValueError):
        normalize_expected_counts({"2026-09-07T05:00:00": 10})


def test_non_integer_expected_count_is_refused():
    with pytest.raises(TypeError):
        normalize_expected_counts({"2026-09-07T05:00:00Z": "10"})


def test_negative_expected_count_is_refused():
    with pytest.raises(ValueError):
        normalize_expected_counts({"2026-09-07T05:00:00Z": -1})


# classify_hour edge cases


@pytest.mark.parametrize(
    ("expected", "raw", "dedup", "classification"),
    [
        (1000, 1000, 1000, HOUR_COMPLETE),
        (1000, 400, 400, HOUR_PARTIAL),
        (1000, 12_000, 400, HOUR_PARTIAL),
        (1000, 0, 0, HOUR_MISSING),
        (1000, 1500, 1500, HOUR_OVERFULL),
        (None, 10, 10, HOUR_UNKNOWN),
        (0, 0, 0, HOUR_COMPLETE),
    ],
)
def test_classify_hour(expected, raw, dedup, classification):
    assert classify_hour(expected, raw, dedup) == classification


def test_dedup_above_raw_is_impossible():
    with pytest.raises(ValueError):
        classify_hour(10, 5, 9)


def test_negative_counts_are_refused():
    with pytest.raises(ValueError):
        classify_hour(10, -1, 0)


# expected-count sources


def test_expected_counts_from_publish_checkpoint():
    document = {
        "topic": "github.events",
        "published": {
            "2026-09-08T00:00:00Z": {"events": 83_301, "published_at": "..."},
            "2026-09-08T01:00:00Z": {"events": 83_456, "published_at": "..."},
        },
    }

    assert expected_counts_from_publish_checkpoint(document) == {
        "2026-09-08T00:00:00Z": 83_301,
        "2026-09-08T01:00:00Z": 83_456,
    }


def test_publish_checkpoint_without_published_is_refused():
    with pytest.raises(TypeError):
        expected_counts_from_publish_checkpoint({"topic": "github.events"})


def test_publish_checkpoint_alone_leaves_failed_hours_unknown():
    """The checkpoint records successes, so it cannot describe the failures.

    This is why `--expected-counts` exists and why it wins: the hours a
    recovery cares about are precisely the ones the checkpoint omits.
    """

    document = {"published": {"2026-09-07T00:00:00Z": {"events": 1000}}}
    checkpoint = expected_counts_from_publish_checkpoint(document)
    _, observed = complete_day()

    report = verify(checkpoint, observed)

    assert report["summary"]["classification_counts"][HOUR_UNKNOWN] == 23
    assert report["result"] == "FAIL"


def test_explicit_expected_counts_win_over_the_checkpoint():
    merged = merge_expected_counts(
        {"2026-09-07T00:00:00Z": 42},
        {"2026-09-07T00:00:00Z": 1000, "2026-09-07T01:00:00Z": 7},
    )

    assert merged == {"2026-09-07T00:00:00Z": 42, "2026-09-07T01:00:00Z": 7}


# the report is JSON a runbook step can act on


def test_report_is_json_serializable():
    expected, observed = complete_day()
    rendered = json.loads(json.dumps(verify(expected, observed)))

    assert rendered["result"] == "PASS"
    assert len(rendered["hours"]) == 24


def test_empty_report_does_not_pass():
    assert summarize_reports([])["passed"] is False
