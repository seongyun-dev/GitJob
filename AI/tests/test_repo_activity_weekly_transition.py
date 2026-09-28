"""Spark-free tests for the transition week (S15P21E102-295).

2026-09-01 is a Tuesday, so September's first Monday-start week begins
2026-08-31: one Historical Raw day and six Streaming days.  `validate_period`
refuses that period for both existing readers and is right to -- the guard is
what stops an hour being counted twice.  The third format is the narrow
exception, and these tests are the fence around it.

The regressions at the bottom matter as much as the new cases: a transition
mode that quietly widened what `raw-json` or `stream-parquet` accept would have
removed the guard rather than worked around it.
"""

import pytest
from jobs.repo_activity_weekly import (
    INPUT_FORMAT_RAW_JSON,
    INPUT_FORMAT_STREAM_PARQUET,
    INPUT_FORMAT_TRANSITION,
    SUPPORTED_HISTORICAL_CUTOFF,
    SUPPORTED_TRANSITION_WEEK_STARTS,
    aggregate_weekly_rows,
    build_parser,
    expected_raw_hour_files,
    expected_stream_hours,
    missing_raw_hour_files,
    missing_stream_hours,
    normalize_raw_rows,
    normalize_transition_rows,
    resolve_input_path,
    transition_split,
    validate_period,
    validate_transition_week,
    week_is_fully_within_period,
)

WEEK_START = "2026-08-31T00:00:00Z"
WEEK_END = "2026-09-07T00:00:00Z"
BOUNDARY = "2026-09-01T00:00:00Z"


def raw_event(repo_id, repo_name, created_at, event_type="PushEvent"):
    return {
        "repo": {"id": repo_id, "name": repo_name},
        "type": event_type,
        "created_at": created_at,
    }


def stream_event(repo_id, repo_name, occurred_at, source_id, event_type="PushEvent"):
    import json

    return {
        "source": "gharchive",
        "source_id": source_id,
        "schema_version": "1",
        "event_type": event_type,
        "occurred_at": occurred_at,
        "payload": json.dumps({"repo": {"id": repo_id, "name": repo_name}}),
    }


# --------------------------------------------------------------------------
# the period contract
# --------------------------------------------------------------------------


def test_transition_week_is_accepted():
    validate_period(WEEK_START, WEEK_END, input_format=INPUT_FORMAT_TRANSITION)

    assert validate_transition_week(WEEK_START, WEEK_END) == ("2026-08-31", BOUNDARY)


def test_boundary_defaults_to_the_historical_cutoff():
    assert SUPPORTED_HISTORICAL_CUTOFF == BOUNDARY
    assert SUPPORTED_TRANSITION_WEEK_STARTS == ("2026-08-31",)


def test_transition_split_meets_exactly_at_the_boundary():
    (raw_start, raw_end), (stream_start, stream_end) = transition_split(
        WEEK_START, WEEK_END
    )

    assert (raw_start, raw_end) == (WEEK_START, BOUNDARY)
    assert (stream_start, stream_end) == (BOUNDARY, WEEK_END)
    # half-open and adjoining: no hour belongs to both readers
    assert raw_end == stream_start


def test_period_that_does_not_straddle_is_refused():
    """A transition run over one side only is the same double-count risk."""

    with pytest.raises(ValueError, match="straddle"):
        validate_period(
            "2026-09-07T00:00:00Z",
            "2026-09-14T00:00:00Z",
            input_format=INPUT_FORMAT_TRANSITION,
        )
    with pytest.raises(ValueError, match="straddle"):
        validate_period(
            "2026-08-24T00:00:00Z",
            "2026-08-31T00:00:00Z",
            input_format=INPUT_FORMAT_TRANSITION,
        )


def test_non_monday_transition_period_is_refused():
    with pytest.raises(ValueError, match="Monday"):
        validate_transition_week("2026-08-30T00:00:00Z", "2026-09-06T00:00:00Z")


def test_period_that_is_not_seven_days_is_refused():
    with pytest.raises(ValueError, match="seven-day"):
        validate_transition_week("2026-08-31T00:00:00Z", "2026-09-14T00:00:00Z")


def test_unsupported_transition_week_is_refused():
    """Mixed input is granted to a named week, not to any straddling period."""

    with pytest.raises(ValueError, match="not supported for week_start"):
        validate_transition_week(
            "2026-06-29T00:00:00Z",
            "2026-07-06T00:00:00Z",
            boundary="2026-07-01T00:00:00Z",
        )


def test_transition_has_no_default_input_path():
    assert resolve_input_path(None, INPUT_FORMAT_TRANSITION) == ""
    assert resolve_input_path("hdfs:///x", INPUT_FORMAT_TRANSITION) == "hdfs:///x"


# --------------------------------------------------------------------------
# coverage gates, one per side
# --------------------------------------------------------------------------


def test_raw_side_expects_twenty_four_hourly_files():
    names = expected_raw_hour_files(WEEK_START, BOUNDARY)

    assert len(names) == 24
    assert names[0] == "2026-08-31-0.json.gz"
    assert names[-1] == "2026-08-31-23.json.gz"


def test_complete_raw_side_has_no_missing_files():
    observed = [
        f"hdfs:///gitjob/raw/gharchive/dt=2026-08-31/{name}"
        for name in expected_raw_hour_files(WEEK_START, BOUNDARY)
    ]

    assert missing_raw_hour_files(observed, WEEK_START, BOUNDARY) == ()


def test_missing_raw_hour_is_reported_by_name():
    """`--expected-files` says 23 of 24; this says which one to fetch."""

    names = list(expected_raw_hour_files(WEEK_START, BOUNDARY))
    names.remove("2026-08-31-5.json.gz")

    assert missing_raw_hour_files(names, WEEK_START, BOUNDARY) == (
        "2026-08-31-5.json.gz",
    )


def test_absent_raw_day_reports_every_hour():
    assert len(missing_raw_hour_files([], WEEK_START, BOUNDARY)) == 24


def test_stream_side_expects_one_hundred_forty_four_hours():
    hours = expected_stream_hours(BOUNDARY, WEEK_END)

    assert len(hours) == 144
    assert hours[0] == "2026-09-01T00:00:00Z"
    assert hours[-1] == "2026-09-06T23:00:00Z"


def test_missing_stream_hour_fails_the_stream_side():
    hours = list(expected_stream_hours(BOUNDARY, WEEK_END))
    hours.remove("2026-09-04T21:00:00Z")

    assert missing_stream_hours(hours, BOUNDARY, WEEK_END) == ("2026-09-04T21:00:00Z",)


def test_partial_hour_still_satisfies_the_presence_gate():
    """Why -264's verifier runs first.

    An hour with one surviving row is `observed`, so the coverage gate passes.
    Completeness is the verifier's question, not this gate's, and the runbook
    orders them accordingly.
    """

    hours = expected_stream_hours(BOUNDARY, WEEK_END)

    assert missing_stream_hours(hours, BOUNDARY, WEEK_END) == ()


def test_the_two_gates_do_not_share_a_notion_of_complete():
    """Raw counts files, the stream counts hours, and neither substitutes."""

    assert len(expected_raw_hour_files(WEEK_START, BOUNDARY)) == 24
    assert len(expected_stream_hours(BOUNDARY, WEEK_END)) == 144


# --------------------------------------------------------------------------
# the union, and what it produces
# --------------------------------------------------------------------------


def test_transition_union_aggregates_into_one_week():
    raw_rows = [
        raw_event(1, "a/b", "2026-08-31T01:00:00Z"),
        raw_event(1, "a/b", "2026-08-31T02:00:00Z"),
        raw_event(2, "c/d", "2026-08-31T03:00:00Z"),
    ]
    stream_rows = [
        stream_event(1, "a/b", "2026-09-02T01:00:00Z", "2026-09-02T01:00:00Z/1"),
        stream_event(3, "e/f", "2026-09-06T23:00:00Z", "2026-09-06T23:00:00Z/2"),
    ]

    rows = aggregate_weekly_rows(normalize_transition_rows(raw_rows, stream_rows))

    assert {row["week_start"] for row in rows} == {"2026-08-31"}
    assert {(row["repo_id"], row["event_count"]) for row in rows} == {
        (1, 3),
        (2, 1),
        (3, 1),
    }


def test_output_schema_is_the_same_as_a_normal_week():
    raw_rows = [raw_event(1, "a/b", "2026-08-31T01:00:00Z")]
    stream_rows = [
        stream_event(1, "a/b", "2026-09-02T01:00:00Z", "2026-09-02T01:00:00Z/1")
    ]

    transition = aggregate_weekly_rows(normalize_transition_rows(raw_rows, stream_rows))
    ordinary = aggregate_weekly_rows(normalize_raw_rows(raw_rows))

    assert set(transition[0]) == set(ordinary[0])


def test_week_end_is_exclusive_and_the_week_is_fully_within_the_period():
    assert week_is_fully_within_period("2026-08-31", WEEK_START, WEEK_END) is True


def test_stream_rows_are_deduplicated_and_raw_rows_are_not_touched():
    """Re-sending only exists on the stream side, so only that side dedups."""

    duplicate = stream_event(1, "a/b", "2026-09-02T01:00:00Z", "2026-09-02T01:00:00Z/1")
    raw_rows = [
        raw_event(1, "a/b", "2026-08-31T01:00:00Z"),
        raw_event(1, "a/b", "2026-08-31T01:00:00Z"),
    ]

    rows = aggregate_weekly_rows(
        normalize_transition_rows(raw_rows, [duplicate, dict(duplicate)])
    )

    # two identical Raw lines are two events; two identical envelopes are one
    assert rows[0]["event_count"] == 3


def test_raw_event_at_or_after_the_boundary_is_refused():
    """It belongs to the stream half; counting it here counts it twice."""

    with pytest.raises(ValueError, match="at or after the transition boundary"):
        normalize_raw_rows([raw_event(1, "a/b", "2026-09-01T00:00:00Z")])


def test_stream_event_below_the_boundary_is_dropped_by_the_existing_guard():
    rows = normalize_transition_rows(
        [],
        [stream_event(1, "a/b", "2026-08-31T23:00:00Z", "2026-08-31T23:00:00Z/1")],
    )

    assert rows == []


def test_the_two_halves_share_no_row():
    """Disjoint in time, so the union is a concatenation, not a merge."""

    raw_rows = [raw_event(1, "a/b", "2026-08-31T23:00:00Z")]
    stream_rows = [
        stream_event(1, "a/b", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z/1")
    ]

    rows = normalize_transition_rows(raw_rows, stream_rows)

    assert len(rows) == 2
    assert [row["created_at"] for row in rows] == [
        "2026-08-31T23:00:00Z",
        "2026-09-01T00:00:00Z",
    ]


# --------------------------------------------------------------------------
# regressions -- the existing two formats must not have moved
# --------------------------------------------------------------------------


def test_pre_cutoff_raw_week_still_behaves():
    validate_period(
        "2026-08-24T00:00:00Z",
        "2026-08-31T00:00:00Z",
        input_format=INPUT_FORMAT_RAW_JSON,
    )
    with pytest.raises(ValueError, match="exceeds exclusive historical_cutoff"):
        validate_period(WEEK_START, WEEK_END, input_format=INPUT_FORMAT_RAW_JSON)


def test_post_cutoff_stream_week_still_behaves():
    validate_period(
        "2026-09-07T00:00:00Z",
        "2026-09-14T00:00:00Z",
        input_format=INPUT_FORMAT_STREAM_PARQUET,
    )
    with pytest.raises(ValueError, match="precedes historical_cutoff"):
        validate_period(WEEK_START, WEEK_END, input_format=INPUT_FORMAT_STREAM_PARQUET)


def test_historical_monthly_period_still_behaves():
    validate_period(
        "2026-08-01T00:00:00Z",
        "2026-09-01T00:00:00Z",
        input_format=INPUT_FORMAT_RAW_JSON,
    )


def test_existing_default_input_paths_are_unchanged():
    assert resolve_input_path(None, INPUT_FORMAT_RAW_JSON).endswith("*.json.gz")
    assert resolve_input_path(None, INPUT_FORMAT_STREAM_PARQUET).endswith(
        "stream/github.events"
    )


# --------------------------------------------------------------------------
# the command line
# --------------------------------------------------------------------------


def test_parser_accepts_the_transition_format():
    arguments = build_parser().parse_args(
        [
            "--input-format",
            INPUT_FORMAT_TRANSITION,
            "--raw-input",
            "hdfs:///gitjob/raw/gharchive/dt=2026-08-31/*.json.gz",
            "--output",
            "hdfs:///out",
            "--period-start",
            WEEK_START,
            "--period-end",
            WEEK_END,
        ]
    )

    assert arguments.input_format == INPUT_FORMAT_TRANSITION
    assert arguments.transition_boundary == BOUNDARY
    assert arguments.stream_input.endswith("stream/github.events")


def test_parser_defaults_are_unchanged_for_the_existing_formats():
    arguments = build_parser().parse_args(["--output", "hdfs:///out"])

    assert arguments.input_format == INPUT_FORMAT_RAW_JSON
    assert arguments.expected_files == 744
