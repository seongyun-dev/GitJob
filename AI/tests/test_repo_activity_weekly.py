"""Spark-free tests for the weekly Repo Activity producer (S15P21E102-166).

Everything the job decides about a row — which week an event belongs to, which
events are dropped, which name a renamed repository keeps, and whether one
week's slice is something the C exporter will accept — lives in pure helpers so
it can be asserted here.  The Spark code path performs the same aggregation with
``groupBy`` and ``date_trunc('week', ...)`` under a UTC session timezone.
"""

import json

import pytest
from jobs.repo_activity_weekly import (
    ACTIVITY_COLUMNS,
    HISTORICAL_CUTOFF,
    HISTORICAL_START,
    INPUT_FORMAT_RAW_JSON,
    INPUT_FORMAT_STREAM_PARQUET,
    activity_rows_for_week,
    aggregate_weekly_rows,
    assert_week_slice_is_consumable,
    expected_stream_hours,
    expected_week_starts,
    format_stream_hour,
    join_coverage_row,
    load_repo_ids,
    missing_stream_hours,
    normalize_stream_rows,
    parse_event_timestamp,
    parse_join_ids_argument,
    parse_stream_payload,
    resolve_input_path,
    stream_hour_key,
    validate_input_format,
    validate_period,
    validate_week_start,
    week_is_fully_within_period,
    week_start_of,
)

# 2026-08-03 is a Monday; 2026-08-01 is the Saturday of the week before it.
MONDAY = "2026-08-03"
NEXT_MONDAY = "2026-08-10"


def event(repo_id, repo_name, created_at):
    return {"repo_id": repo_id, "repo_name": repo_name, "created_at": created_at}


# --- week boundary ---------------------------------------------------------


def test_monday_midnight_belongs_to_its_own_week():
    assert week_start_of("2026-08-03T00:00:00Z") == MONDAY


def test_sunday_last_second_stays_in_the_opening_monday_week():
    assert week_start_of("2026-08-09T23:59:59Z") == MONDAY
    assert week_start_of("2026-08-10T00:00:00Z") == NEXT_MONDAY


def test_month_start_falls_in_the_previous_months_week():
    # 2026-08-01 is a Saturday, so the first August events belong to a week
    # that opened in July.  The job keeps them instead of silently dropping a
    # partial week.
    assert week_start_of("2026-08-01T00:00:00Z") == "2026-07-27"


# --- timezone --------------------------------------------------------------


def test_offset_timestamps_are_converted_before_the_week_is_taken():
    # 2026-08-10T02:00+09:00 is 2026-08-09T17:00Z — still the previous week.
    assert week_start_of("2026-08-10T02:00:00+09:00") == MONDAY
    assert week_start_of("2026-08-10T02:00:00Z") == NEXT_MONDAY


def test_naive_timestamps_are_rejected_rather_than_assumed_utc():
    with pytest.raises(ValueError, match="timezone"):
        parse_event_timestamp("2026-08-10T02:00:00")


@pytest.mark.parametrize("value", ["", "   ", None, 20260810, "not-a-timestamp"])
def test_unusable_created_at_is_rejected(value):
    with pytest.raises(ValueError):
        parse_event_timestamp(value)


# --- week_start contract ---------------------------------------------------


def test_week_start_must_be_a_monday():
    assert validate_week_start(MONDAY).isoformat() == MONDAY
    with pytest.raises(ValueError, match="Monday"):
        validate_week_start("2026-08-04")


@pytest.mark.parametrize("value", ["2026-8-3", "20260803", "2026-08-03T00:00:00Z"])
def test_week_start_must_be_a_canonical_iso_date(value):
    with pytest.raises(ValueError):
        validate_week_start(value)


def test_august_period_spans_six_weeks_two_of_them_partial():
    weeks = expected_week_starts(HISTORICAL_START, HISTORICAL_CUTOFF)

    assert weeks == (
        "2026-07-27",
        "2026-08-03",
        "2026-08-10",
        "2026-08-17",
        "2026-08-24",
        "2026-08-31",
    )
    complete = [
        week
        for week in weeks
        if week_is_fully_within_period(week, HISTORICAL_START, HISTORICAL_CUTOFF)
    ]
    assert complete == ["2026-08-03", "2026-08-10", "2026-08-17", "2026-08-24"]


def test_period_outside_the_validated_raw_window_is_refused():
    with pytest.raises(ValueError, match="precedes historical_start"):
        validate_period("2026-01-01T00:00:00Z", HISTORICAL_CUTOFF)
    with pytest.raises(ValueError, match="exceeds exclusive historical_cutoff"):
        validate_period(HISTORICAL_START, "2026-10-01T00:00:00Z")


# --- aggregation -----------------------------------------------------------


def test_events_group_by_repo_and_week():
    rows = aggregate_weekly_rows(
        [
            event(10, "o/a", "2026-08-03T01:00:00Z"),
            event(10, "o/a", "2026-08-09T23:00:00Z"),
            event(10, "o/a", "2026-08-10T00:00:00Z"),
            event(20, "o/b", "2026-08-05T00:00:00Z"),
        ]
    )

    assert [
        (row["repo_id"], row["week_start"], row["event_count"]) for row in rows
    ] == [
        (10, MONDAY, 2),
        (20, MONDAY, 1),
        (10, NEXT_MONDAY, 1),
    ]


def test_one_row_per_repo_id_within_a_week():
    rows = aggregate_weekly_rows(
        [event(10, "o/a", "2026-08-03T01:00:00Z") for _ in range(5)]
    )

    assert len(rows) == 1
    assert rows[0]["event_count"] == 5


def test_renamed_repository_keeps_the_name_from_its_latest_event_that_week():
    rows = aggregate_weekly_rows(
        [
            event(10, "o/old", "2026-08-03T01:00:00Z"),
            event(10, "o/new", "2026-08-06T01:00:00Z"),
            event(10, "o/old", "2026-08-04T01:00:00Z"),
        ]
    )

    assert rows[0]["repo_name"] == "o/new"
    assert rows[0]["event_count"] == 3
    assert rows[0]["name_count"] == 2


def test_ties_on_the_same_instant_resolve_deterministically():
    same_instant = "2026-08-03T01:00:00Z"
    first = aggregate_weekly_rows(
        [event(10, "o/a", same_instant), event(10, "o/b", same_instant)]
    )
    reversed_order = aggregate_weekly_rows(
        [event(10, "o/b", same_instant), event(10, "o/a", same_instant)]
    )

    assert first == reversed_order
    assert first[0]["repo_name"] == "o/b"


def test_identical_input_in_any_order_produces_identical_output():
    events = [
        event(30, "o/c", "2026-08-11T05:00:00Z"),
        event(10, "o/a", "2026-08-03T01:00:00Z"),
        event(20, "o/b", "2026-08-04T02:00:00Z"),
        event(10, "o/a", "2026-08-09T23:59:59Z"),
    ]

    assert aggregate_weekly_rows(events) == aggregate_weekly_rows(
        list(reversed(events))
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"repo_id": None, "repo_name": "o/a", "created_at": "2026-08-03T01:00:00Z"},
        {"repo_id": 0, "repo_name": "o/a", "created_at": "2026-08-03T01:00:00Z"},
        {"repo_id": -1, "repo_name": "o/a", "created_at": "2026-08-03T01:00:00Z"},
        {"repo_id": True, "repo_name": "o/a", "created_at": "2026-08-03T01:00:00Z"},
        {"repo_id": "10", "repo_name": "o/a", "created_at": "2026-08-03T01:00:00Z"},
        {"repo_id": 10, "repo_name": None, "created_at": "2026-08-03T01:00:00Z"},
        {"repo_id": 10, "repo_name": "   ", "created_at": "2026-08-03T01:00:00Z"},
        {"repo_id": 10, "repo_name": "o/a", "created_at": None},
        {"repo_id": 10, "repo_name": "o/a", "created_at": "2026-08-03T01:00:00"},
    ],
)
def test_unusable_events_are_dropped_not_counted(bad):
    rows = aggregate_weekly_rows([event(99, "o/keep", "2026-08-03T01:00:00Z"), bad])

    assert [row["repo_id"] for row in rows] == [99]
    assert rows[0]["event_count"] == 1


# --- the slice the C exporter reads ---------------------------------------


def test_week_slice_carries_exactly_the_consumer_columns():
    rows = aggregate_weekly_rows(
        [
            event(10, "o/a", "2026-08-03T01:00:00Z"),
            event(20, "o/b", "2026-08-11T01:00:00Z"),
        ]
    )
    slice_rows = activity_rows_for_week(rows, MONDAY)

    assert [tuple(row) for row in slice_rows] == [ACTIVITY_COLUMNS]
    assert slice_rows == [
        {"repo_id": 10, "repo_name": "o/a", "event_count": 1, "week_start": MONDAY}
    ]
    assert_week_slice_is_consumable(slice_rows)


def test_week_slice_rejects_two_weeks_in_one_read():
    rows = aggregate_weekly_rows(
        [
            event(10, "o/a", "2026-08-03T01:00:00Z"),
            event(10, "o/a", "2026-08-11T01:00:00Z"),
        ]
    )

    with pytest.raises(ValueError, match="exactly one week_start"):
        assert_week_slice_is_consumable(
            [{column: row[column] for column in ACTIVITY_COLUMNS} for row in rows]
        )


def test_week_slice_rejects_a_duplicated_repo_id():
    duplicated = [
        {"repo_id": 10, "repo_name": "o/a", "event_count": 1, "week_start": MONDAY},
        {"repo_id": 10, "repo_name": "o/a", "event_count": 2, "week_start": MONDAY},
    ]

    with pytest.raises(ValueError, match="duplicate repo_id"):
        assert_week_slice_is_consumable(duplicated)


def test_week_slice_satisfies_the_exporter_period_binding():
    from jobs.export_c_archive_activity import validate_source_period_binding

    rows = aggregate_weekly_rows([event(10, "o/a", "2026-08-05T01:00:00Z")])
    slice_rows = activity_rows_for_week(rows, MONDAY)

    validate_source_period_binding(
        MONDAY,
        "WEEK",
        observed_periods=tuple({row["week_start"] for row in slice_rows}),
    )
    with pytest.raises(ValueError):
        validate_source_period_binding(
            NEXT_MONDAY,
            "WEEK",
            observed_periods=tuple({row["week_start"] for row in slice_rows}),
        )


def test_week_slice_rows_pass_the_c_trend_row_contract():
    import io

    from trend.archive import iter_bounded_activity_stream

    rows = aggregate_weekly_rows(
        [
            event(10, "o/a", "2026-08-03T01:00:00Z"),
            event(20, "o/b", "2026-08-04T01:00:00Z"),
        ]
    )
    # What the exporter writes out of one week directory, read back by the
    # consumer's own parser rather than by an assertion written here.
    ndjson = "\n".join(json.dumps(row) for row in activity_rows_for_week(rows, MONDAY))

    accepted = list(
        iter_bounded_activity_stream(
            io.StringIO(ndjson),
            suffix=".ndjson",
            granularity="WEEK",
            max_rows=100,
        )
    )

    assert [
        (row["repo_id"], row["week_start"], row["event_count"]) for row in accepted
    ] == [
        (10, MONDAY, 1),
        (20, MONDAY, 1),
    ]


# --- Top-N / COMPLETE JOIN cohorts ----------------------------------------


def _candidates_file(tmp_path, repo_ids):
    path = tmp_path / "candidates.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "repo-fetch-candidates/v1",
                "input_root": "hdfs:///gitjob/parquet/github/repo_activity/period=2026-08",
                "candidates": [
                    {"repo_id": repo_id, "repo_name": f"o/{repo_id}", "rank": rank}
                    for rank, repo_id in enumerate(repo_ids, start=1)
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_top_n_candidate_envelope_loads_the_same_ids_the_exporter_uses(tmp_path):
    path = _candidates_file(tmp_path, [30, 10, 20])

    assert load_repo_ids(path, max_rows=10) == (10, 20, 30)


def test_snapshot_envelope_uses_the_github_repo_id_field(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "github-repo-snapshot/v1",
                "records": [
                    {"github_repo_id": 20, "collection_status": "COMPLETE"},
                    {"github_repo_id": 10, "collection_status": "COMPLETE"},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert load_repo_ids(path, max_rows=10) == (10, 20)


def test_join_coverage_counts_repositories_not_rows():
    rows = aggregate_weekly_rows(
        [
            event(10, "o/a", "2026-08-03T01:00:00Z"),
            event(10, "o/a", "2026-08-11T01:00:00Z"),
            event(20, "o/b", "2026-08-04T01:00:00Z"),
        ]
    )

    coverage = join_coverage_row("TOP_N", [10, 20, 30], rows)

    assert coverage["cohort_repo_count"] == 3
    assert coverage["matched_repo_count"] == 2
    assert coverage["missing_repo_count"] == 1
    assert coverage["matched_row_count"] == 3
    assert coverage["matched_event_count"] == 3
    assert coverage["active_week_count"] == 2
    assert coverage["coverage_ratio"] == pytest.approx(2 / 3)


def test_full_cohort_coverage_is_reported_as_one():
    rows = aggregate_weekly_rows([event(10, "o/a", "2026-08-03T01:00:00Z")])

    assert join_coverage_row("COMPLETE", [10], rows)["coverage_ratio"] == 1.0


def test_join_cohort_argument_is_label_and_path():
    label, path = parse_join_ids_argument("TOP20K=/approved/top20k.json")

    assert label == "TOP20K"
    assert path.name == "top20k.json"


@pytest.mark.parametrize("value", ["TOP20K", "=/approved/x.json", "TOP20K=", "A B=/x"])
def test_malformed_join_cohort_arguments_are_refused(value):
    with pytest.raises(ValueError):
        parse_join_ids_argument(value)


# --- the stream input (S15P21E102-224) -------------------------------------
#
# Everything below drives the pure helpers that mirror the Spark stream path.
# No Spark, no HDFS, no broker: `normalize_stream_rows` performs the same
# source filter, dedup, payload lift and cutoff drop that `run_job` expresses
# with DataFrame operations, and its output is fed to the same
# `aggregate_weekly_rows` the Raw path uses.

# The first hour at or after the cutoff, and the Monday of its week.
STREAM_HOUR = "2026-09-01T00:00:00Z"
STREAM_MONDAY = "2026-08-31"


def stream_row(
    event_id,
    repo_id=10,
    repo_name="octo/app",
    occurred_at="2026-09-01T00:30:00Z",
    hour_key=STREAM_HOUR,
    event_type="PushEvent",
    payload=None,
    source="gharchive",
    schema_version="gitjob.event/v1",
):
    """One row of C1's archive, shaped like `ARCHIVE_COLUMNS`."""

    if payload is None:
        body = {"id": str(event_id), "type": event_type, "created_at": occurred_at}
        if repo_id is not None or repo_name is not None:
            repo = {}
            if repo_id is not None:
                repo["id"] = repo_id
            if repo_name is not None:
                repo["name"] = repo_name
            body["repo"] = repo
        payload = json.dumps(body)
    return {
        "source": source,
        "source_id": f"{hour_key}/{event_id}",
        "schema_version": schema_version,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "payload": payload,
    }


# --- payload parsing -------------------------------------------------------


def test_stream_payload_yields_the_original_event():
    rows = normalize_stream_rows([stream_row("1")])

    assert rows == [
        {
            "repo_id": 10,
            "repo_name": "octo/app",
            "event_type": "PushEvent",
            "created_at": "2026-09-01T00:30:00Z",
        }
    ]


def test_stream_payload_feeds_the_raw_aggregation_unchanged():
    """The point of the whole change: one aggregator, two readers."""

    rows = aggregate_weekly_rows(normalize_stream_rows([stream_row("1")]))

    assert activity_rows_for_week(rows, STREAM_MONDAY) == [
        {
            "repo_id": 10,
            "repo_name": "octo/app",
            "event_count": 1,
            "week_start": STREAM_MONDAY,
        }
    ]


def test_payload_may_arrive_already_decoded():
    decoded = {
        "id": "1",
        "type": "PushEvent",
        "created_at": "2026-09-01T00:30:00Z",
        "repo": {"id": 10, "name": "octo/app"},
    }

    assert parse_stream_payload(decoded) == decoded


@pytest.mark.parametrize("value", ["", "   ", "not json", "[1, 2]", '"text"', None, 7])
def test_malformed_payloads_are_refused_by_the_parser(value):
    with pytest.raises(ValueError):
        parse_stream_payload(value)


def test_malformed_payload_is_kept_but_drops_out_of_the_aggregate():
    """Dropping happens in one place - `aggregate_weekly_rows` - not two."""

    rows = normalize_stream_rows([stream_row("1", payload="{ broken")])

    assert rows == [
        {
            "repo_id": None,
            "repo_name": None,
            "event_type": "PushEvent",
            "created_at": "2026-09-01T00:30:00Z",
        }
    ]
    assert aggregate_weekly_rows(rows) == []


def test_event_without_repo_is_excluded():
    rows = normalize_stream_rows([stream_row("1", repo_id=None, repo_name=None)])

    assert rows[0]["repo_id"] is None
    assert aggregate_weekly_rows(rows) == []


def test_event_without_repo_name_is_excluded():
    rows = normalize_stream_rows([stream_row("1", repo_name=None)])

    assert rows[0]["repo_id"] == 10
    assert rows[0]["repo_name"] is None
    assert aggregate_weekly_rows(rows) == []


def test_non_integer_repo_id_is_excluded():
    rows = normalize_stream_rows([stream_row("1", repo_id="10")])

    assert rows[0]["repo_id"] is None
    assert aggregate_weekly_rows(rows) == []


def test_event_type_comes_from_the_promoted_column():
    """`event_type` is already a column; the payload is not re-read for it."""

    row = stream_row("1", event_type="WatchEvent")
    row["payload"] = json.dumps(
        {
            "id": "1",
            "type": "IgnoredByThisJob",
            "created_at": "2026-09-01T00:30:00Z",
            "repo": {"id": 10, "name": "octo/app"},
        }
    )

    assert normalize_stream_rows([row])[0]["event_type"] == "WatchEvent"


def test_created_at_comes_from_the_promoted_occurred_at():
    row = stream_row("1", occurred_at="2026-09-07T12:00:00Z")
    row["payload"] = json.dumps(
        {
            "id": "1",
            "type": "PushEvent",
            "created_at": "2026-09-01T00:30:00Z",
            "repo": {"id": 10, "name": "octo/app"},
        }
    )

    rows = aggregate_weekly_rows(normalize_stream_rows([row]))

    assert rows[0]["week_start"] == "2026-09-07"


def test_another_topics_archive_is_not_aggregated():
    assert normalize_stream_rows([stream_row("1", source="stackoverflow")]) == []


# --- replay and dedup ------------------------------------------------------


def test_replaying_the_same_event_does_not_change_the_count():
    once = aggregate_weekly_rows(normalize_stream_rows([stream_row("1")]))
    twice = aggregate_weekly_rows(
        normalize_stream_rows([stream_row("1"), stream_row("1")])
    )

    assert once == twice
    assert twice[0]["event_count"] == 1


def test_replaying_a_whole_batch_does_not_change_the_counts():
    """The publisher re-sends an hour it could not finish; 4.1 absorbs it."""

    batch = [stream_row("1"), stream_row("2"), stream_row("3", repo_id=20)]

    once = aggregate_weekly_rows(normalize_stream_rows(batch))
    replayed = aggregate_weekly_rows(normalize_stream_rows(batch + batch))

    assert once == replayed
    assert {row["repo_id"]: row["event_count"] for row in replayed} == {10: 2, 20: 1}


def test_the_same_event_id_in_a_different_hour_is_a_different_event():
    """`source_id` carries the hour, so the triple separates the two."""

    rows = normalize_stream_rows(
        [
            stream_row("1", hour_key="2026-09-01T00:00:00Z"),
            stream_row(
                "1",
                hour_key="2026-09-01T01:00:00Z",
                occurred_at="2026-09-01T01:30:00Z",
            ),
        ]
    )

    assert len(rows) == 2


def test_a_new_schema_version_is_not_deduplicated_away():
    rows = normalize_stream_rows(
        [stream_row("1"), stream_row("1", schema_version="gitjob.event/v2")]
    )

    assert len(rows) == 2


def test_aggregation_is_deterministic_regardless_of_row_order():
    batch = [
        stream_row("1", occurred_at="2026-09-01T00:30:00Z"),
        stream_row("2", repo_id=20, occurred_at="2026-09-02T00:30:00Z"),
        stream_row("3", occurred_at="2026-09-03T00:30:00Z"),
    ]

    forward = aggregate_weekly_rows(normalize_stream_rows(batch))
    backward = aggregate_weekly_rows(normalize_stream_rows(list(reversed(batch))))

    assert forward == backward


# --- the cutoff boundary ---------------------------------------------------


def test_an_event_just_before_the_cutoff_belongs_to_the_raw_path():
    rows = normalize_stream_rows([stream_row("1", occurred_at="2026-08-31T23:59:59Z")])

    assert rows == []


def test_an_event_exactly_at_the_cutoff_belongs_to_the_stream():
    rows = normalize_stream_rows([stream_row("1", occurred_at=HISTORICAL_CUTOFF)])

    assert len(rows) == 1


def test_an_event_after_the_cutoff_belongs_to_the_stream():
    rows = normalize_stream_rows([stream_row("1", occurred_at="2026-09-01T00:00:01Z")])

    assert len(rows) == 1


def test_the_two_readers_cannot_claim_the_same_period():
    """The structural half of "no hour is counted twice"."""

    validate_period("2026-08-01T00:00:00Z", HISTORICAL_CUTOFF)
    validate_period(
        HISTORICAL_CUTOFF,
        "2026-10-01T00:00:00Z",
        input_format=INPUT_FORMAT_STREAM_PARQUET,
    )

    with pytest.raises(ValueError, match="historical_cutoff"):
        validate_period("2026-08-01T00:00:00Z", "2026-10-01T00:00:00Z")
    with pytest.raises(ValueError, match="precedes historical_cutoff"):
        validate_period(
            "2026-08-25T00:00:00Z",
            "2026-10-01T00:00:00Z",
            input_format=INPUT_FORMAT_STREAM_PARQUET,
        )


def test_the_stream_period_has_no_upper_bound():
    """Hours keep arriving; only Raw is a closed window."""

    validate_period(
        "2027-01-01T00:00:00Z",
        "2027-02-01T00:00:00Z",
        input_format=INPUT_FORMAT_STREAM_PARQUET,
    )


def test_an_unknown_input_format_is_refused():
    with pytest.raises(ValueError, match="input_format"):
        validate_input_format("orc")


# --- the completeness gate -------------------------------------------------


def test_expected_hours_are_every_utc_hour_in_the_period():
    hours = expected_stream_hours(STREAM_HOUR, "2026-09-02T00:00:00Z")

    assert len(hours) == 24
    assert hours[0] == STREAM_HOUR
    assert hours[-1] == "2026-09-01T23:00:00Z"


def test_expected_hours_match_the_recorded_month_counts():
    """744 and 720 are the numbers -105/-179 counted for Raw."""

    assert len(expected_stream_hours(STREAM_HOUR, "2026-10-01T00:00:00Z")) == 720
    assert (
        len(expected_stream_hours("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"))
        == 744
    )


def test_a_complete_day_reports_no_missing_hours():
    observed = expected_stream_hours(STREAM_HOUR, "2026-09-02T00:00:00Z")

    assert missing_stream_hours(observed, STREAM_HOUR, "2026-09-02T00:00:00Z") == ()


def test_an_hour_that_never_reached_kafka_is_reported():
    observed = list(expected_stream_hours(STREAM_HOUR, "2026-09-02T00:00:00Z"))
    observed.remove("2026-09-01T05:00:00Z")

    missing = missing_stream_hours(observed, STREAM_HOUR, "2026-09-02T00:00:00Z")

    assert missing == ("2026-09-01T05:00:00Z",)


def test_hour_key_comes_from_the_publishers_source_id():
    assert stream_hour_key(f"{STREAM_HOUR}/12345") == STREAM_HOUR


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "2026-09-01T00:00:00Z",
        "2026-09-01T00:00:00Z/",
        "2026-09-01T00:30:00Z/1",
        "not-a-time/1",
    ],
)
def test_a_malformed_source_id_is_not_silently_a_coverage_hole(value):
    with pytest.raises(ValueError):
        stream_hour_key(value)


def test_the_hour_key_shape_matches_the_publisher():
    """Guards the one constant this job repeats instead of importing."""

    from collector.gharchive.historical import format_utc_hour

    moment = parse_event_timestamp("2026-09-01T00:30:00Z")

    assert format_stream_hour(moment) == format_utc_hour(moment)


# --- the consumer contract is unchanged ------------------------------------


def test_stream_weeks_satisfy_the_c_exporter_contract():
    batch = [
        stream_row("1", occurred_at="2026-09-01T00:30:00Z"),
        stream_row("2", repo_id=20, occurred_at="2026-09-01T02:00:00Z"),
        stream_row("3", repo_id=30, occurred_at="2026-09-08T02:00:00Z"),
    ]

    rows = aggregate_weekly_rows(normalize_stream_rows(batch))

    for week in {row["week_start"] for row in rows}:
        slice_rows = activity_rows_for_week(rows, week)
        assert_week_slice_is_consumable(slice_rows)
        for row in slice_rows:
            assert tuple(row) == ACTIVITY_COLUMNS


def test_stream_week_starts_are_mondays():
    rows = aggregate_weekly_rows(
        normalize_stream_rows([stream_row("1", occurred_at="2026-09-06T23:59:59Z")])
    )

    # 2026-09-06 is a Sunday, so it belongs to the week starting 2026-08-31.
    assert rows[0]["week_start"] == "2026-08-31"
    validate_week_start(rows[0]["week_start"])


def test_a_sunday_and_the_following_monday_land_in_different_weeks():
    rows = aggregate_weekly_rows(
        normalize_stream_rows(
            [
                stream_row("1", occurred_at="2026-09-06T23:59:59Z"),
                stream_row("2", occurred_at="2026-09-07T00:00:00Z"),
            ]
        )
    )

    assert [row["week_start"] for row in rows] == ["2026-08-31", "2026-09-07"]


def test_each_reader_defaults_to_its_own_root():
    raw = resolve_input_path(None, INPUT_FORMAT_RAW_JSON)
    stream = resolve_input_path(None, INPUT_FORMAT_STREAM_PARQUET)

    assert raw.startswith("hdfs:///gitjob/raw/gharchive/")
    assert stream == "hdfs:///gitjob/parquet/stream/github.events"
    assert raw != stream


def test_an_explicit_input_path_is_kept():
    assert (
        resolve_input_path("hdfs:///elsewhere", INPUT_FORMAT_STREAM_PARQUET)
        == "hdfs:///elsewhere"
    )
