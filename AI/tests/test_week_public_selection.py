"""S15P21E102-337: a WEEK observation may only use a week-specific PUBLIC.

Reusing a MONTH PUBLIC for a WEEK is what produced
PUBLIC_REPOSITORY_MISSING_ACTIVITY: the denominator is built over a different
period than the activity rows the week carries, so repositories counted in the
month have no row in the week and the week's coverage reads as missing.

These exercise the selection predicate directly. `select_public_snapshot` wraps
it with a DB query whose ordering is unchanged by this issue, and its tests need
an isolated PostgreSQL (`C_COMPUTE_TEST_DATABASE_URL`).
"""

from __future__ import annotations

from datetime import date

from worker.store import _public_payload_covers_week

WEEK = date(2026, 8, 31)  # Monday; the week runs 2026-08-31 .. 2026-09-06


def result_for(*, target_period, start, end, included=True):
    return {
        "records": [
            {
                "included_in_denominator": included,
                "target_period": target_period,
                "activity_period_start": start,
                "activity_period_end": end,
            }
        ]
    }


def test_exact_week_public_covers_the_week():
    assert _public_payload_covers_week(
        result_for(
            target_period="2026-08-31/2026-09-06",
            start="2026-08-31",
            end="2026-09-06",
        ),
        WEEK,
    )


def test_month_public_overlapping_one_day_does_not_cover_the_week():
    """August ends on the Monday the week starts: 1 of its 7 days."""

    assert not _public_payload_covers_week(
        result_for(
            target_period="2026-08-01/2026-08-31",
            start="2026-08-01",
            end="2026-08-31",
        ),
        WEEK,
    )


def test_month_public_containing_the_whole_week_does_not_cover_it():
    """Containment is not enough - the denominator is still monthly."""

    assert not _public_payload_covers_week(
        result_for(
            target_period="2026-08-01/2026-08-31",
            start="2026-08-01",
            end="2026-08-31",
        ),
        date(2026, 8, 24),  # 2026-08-24 .. 2026-08-30, fully inside August
    )


def test_a_different_week_does_not_cover_the_week():
    assert not _public_payload_covers_week(
        result_for(
            target_period="2026-09-07/2026-09-13",
            start="2026-09-07",
            end="2026-09-13",
        ),
        WEEK,
    )


def test_legacy_monthly_shorthand_target_period_does_not_cover_the_week():
    assert not _public_payload_covers_week(
        result_for(
            target_period="2026-08", start="2026-08-31", end="2026-09-06"
        ),
        WEEK,
    )


def test_missing_target_period_does_not_cover_the_week():
    """A record that never says which period it is for cannot be trusted here."""

    assert not _public_payload_covers_week(
        result_for(target_period=None, start="2026-08-31", end="2026-09-06"),
        WEEK,
    )


def test_activity_period_must_match_the_week_exactly():
    assert not _public_payload_covers_week(
        result_for(
            target_period="2026-08-31/2026-09-06",
            start="2026-08-31",
            end="2026-09-05",  # one day short
        ),
        WEEK,
    )


def test_every_included_record_must_match_the_week():
    payload = {
        "records": [
            {
                "included_in_denominator": True,
                "target_period": "2026-08-31/2026-09-06",
                "activity_period_start": "2026-08-31",
                "activity_period_end": "2026-09-06",
            },
            {
                "included_in_denominator": True,
                "target_period": "2026-08-01/2026-08-31",
                "activity_period_start": "2026-08-01",
                "activity_period_end": "2026-08-31",
            },
        ]
    }

    assert not _public_payload_covers_week(payload, WEEK)


def test_records_excluded_from_the_denominator_are_ignored():
    payload = {
        "records": [
            {
                "included_in_denominator": True,
                "target_period": "2026-08-31/2026-09-06",
                "activity_period_start": "2026-08-31",
                "activity_period_end": "2026-09-06",
            },
            {
                "included_in_denominator": False,
                "target_period": "2026-08-01/2026-08-31",
                "activity_period_start": "2026-08-01",
                "activity_period_end": "2026-08-31",
            },
        ]
    }

    assert _public_payload_covers_week(payload, WEEK)


def test_no_included_records_does_not_cover_the_week():
    assert not _public_payload_covers_week(
        result_for(
            target_period="2026-08-31/2026-09-06",
            start="2026-08-31",
            end="2026-09-06",
            included=False,
        ),
        WEEK,
    )


def test_existing_production_weeks_still_covered():
    """The two weeks already flowing through TREND must keep selecting."""

    assert _public_payload_covers_week(
        result_for(
            target_period="2026-03-02/2026-03-08",
            start="2026-03-02",
            end="2026-03-08",
        ),
        date(2026, 3, 2),
    )
    assert _public_payload_covers_week(
        result_for(
            target_period="2026-09-07/2026-09-13",
            start="2026-09-07",
            end="2026-09-13",
        ),
        date(2026, 9, 7),
    )
