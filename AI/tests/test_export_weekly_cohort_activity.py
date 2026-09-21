"""Join rules for the week-activity input `weekly_public_publish_cli` consumes."""

from __future__ import annotations

import json

import pytest
from jobs.export_weekly_cohort_activity import (
    ACTIVITY_COLUMNS,
    render_ndjson,
    select_week_activity,
)

WEEK = "2026-03-09"


def _rows(*pairs):
    return [
        {"repo_id": repo_id, "event_count": events, "week_start": WEEK}
        for repo_id, events in pairs
    ]


def test_only_cohort_repositories_survive_the_join():
    rows = _rows((1, 30), (2, 20), (3, 10))

    selected = select_week_activity(rows, {1, 3}, week_start=WEEK)

    assert [row["repo_id"] for row in selected] == [1, 3]


def test_a_cohort_repository_with_no_row_this_week_is_not_invented():
    # The aggregate is a groupBy over events, so a repository with no activity
    # has no row at all. Emitting a zero for it would put a repository in the
    # week's denominator that did nothing that week.
    rows = _rows((1, 30))

    selected = select_week_activity(rows, {1, 99}, week_start=WEEK)

    assert [row["repo_id"] for row in selected] == [1]


def test_event_count_is_carried_through_unchanged():
    rows = _rows((7, 47530))

    selected = select_week_activity(rows, {7}, week_start=WEEK)

    assert selected[0]["event_count"] == 47530


def test_rows_are_ordered_by_activity_then_repository_id():
    rows = _rows((5, 10), (4, 90), (6, 90))

    selected = select_week_activity(rows, {4, 5, 6}, week_start=WEEK)

    assert [row["repo_id"] for row in selected] == [4, 6, 5]


def test_a_repeated_repository_in_the_aggregate_is_refused():
    rows = _rows((1, 10), (1, 20))

    with pytest.raises(ValueError, match="duplicate"):
        select_week_activity(rows, {1}, week_start=WEEK)


def test_a_row_from_another_week_is_refused():
    rows = _rows((1, 10))
    rows.append({"repo_id": 2, "event_count": 5, "week_start": "2026-03-16"})

    with pytest.raises(ValueError, match="week_start"):
        select_week_activity(rows, {1, 2}, week_start=WEEK)


def test_a_negative_or_non_integer_count_is_refused():
    rows = [{"repo_id": 1, "event_count": -1, "week_start": WEEK}]

    with pytest.raises(ValueError, match="event_count"):
        select_week_activity(rows, {1}, week_start=WEEK)


def test_an_empty_cohort_is_refused_rather_than_silently_emptying_the_week():
    rows = _rows((1, 10))

    with pytest.raises(ValueError, match="cohort"):
        select_week_activity(rows, set(), week_start=WEEK)


def test_the_row_budget_is_bounded():
    rows = _rows(*((repo_id, 1) for repo_id in range(1, 6)))

    with pytest.raises(ValueError, match="max_rows"):
        select_week_activity(rows, set(range(1, 6)), week_start=WEEK, max_rows=4)


def test_ndjson_carries_exactly_the_columns_the_publisher_reads():
    rows = select_week_activity(_rows((2, 5), (1, 9)), {1, 2}, week_start=WEEK)

    body = render_ndjson(rows)

    lines = body.decode("utf-8").splitlines()
    assert len(lines) == 2
    assert set(json.loads(lines[0])) == set(ACTIVITY_COLUMNS)


def test_the_same_input_renders_the_same_bytes():
    first = render_ndjson(
        select_week_activity(_rows((1, 9), (2, 5)), {1, 2}, week_start=WEEK)
    )
    second = render_ndjson(
        select_week_activity(_rows((2, 5), (1, 9)), {1, 2}, week_start=WEEK)
    )

    assert first == second


def test_the_rendered_file_is_accepted_by_the_weekly_publisher(tmp_path):
    # The one contract that matters end to end: whatever this job writes must
    # parse with the reader `weekly_public_publish_cli` uses, with the same
    # repo_id -> event_count mapping. A column rename here would otherwise only
    # surface in production.
    from github.weekly_public_publish_cli import _week_activity

    rows = select_week_activity(_rows((2, 5), (1, 9)), {1, 2}, week_start=WEEK)
    destination = tmp_path / "week-activity.ndjson"
    destination.write_bytes(render_ndjson(rows))

    assert _week_activity(destination, WEEK) == {1: 9, 2: 5}
