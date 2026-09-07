"""Seoul-timezone date handling for Worknet postings."""

from __future__ import annotations

import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")

# Worknet renders dates as 2026-09-07, 2026.09.07 or 2026/09/07, and the
# detail page appends a clock time (2026.09.07 10:15:57).
_DATE_RE = re.compile(
    r"(?P<year>20\d{2})\s*[./-]\s*(?P<month>\d{1,2})\s*[./-]\s*(?P<day>\d{1,2})"
)
_TIME_RE = re.compile(r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?")

# Deadlines that carry no date. Worknet uses these instead of a due date.
OPEN_ENDED_DEADLINE_LABELS = ("채용시까지", "상시채용", "채용시", "수시채용")


def as_seoul(value: datetime) -> datetime:
    """Attach or convert to the Asia/Seoul timezone."""

    if value.tzinfo is None:
        return value.replace(tzinfo=SEOUL)
    return value.astimezone(SEOUL)


def start_of_day(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=SEOUL)


def end_of_day(value: date) -> datetime:
    return datetime.combine(value, time.max, tzinfo=SEOUL)


def date_range_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """Inclusive Seoul-local bounds for a registration-date range."""

    if end < start:
        raise ValueError("end date must not precede start date")
    return start_of_day(start), end_of_day(end)


def parse_date(text: str | None) -> date | None:
    """Extract the first yyyy-mm-dd style date from free text."""

    if not text:
        return None
    match = _DATE_RE.search(text)
    if match is None:
        return None
    try:
        return date(
            int(match["year"]),
            int(match["month"]),
            int(match["day"]),
        )
    except ValueError:
        return None


def parse_datetime(text: str | None) -> datetime | None:
    """Extract a timezone-aware Seoul datetime from free text.

    The contract requires a timezone on every timestamp, so a date without a
    clock time is anchored to local midnight rather than left naive.
    """

    parsed_date = parse_date(text)
    if parsed_date is None:
        return None

    assert text is not None
    time_match = _TIME_RE.search(text)
    if time_match is None:
        return start_of_day(parsed_date)

    hour = int(time_match["hour"])
    minute = int(time_match["minute"])
    second = int(time_match["second"] or 0)
    if hour > 23 or minute > 59 or second > 59:
        return start_of_day(parsed_date)

    return datetime(
        parsed_date.year,
        parsed_date.month,
        parsed_date.day,
        hour,
        minute,
        second,
        tzinfo=SEOUL,
    )


def is_open_ended_deadline(text: str | None) -> bool:
    """True when the deadline label carries no date (채용시까지 등)."""

    if not text:
        return False
    collapsed = text.replace(" ", "")
    return any(label in collapsed for label in OPEN_ENDED_DEADLINE_LABELS)


def format_cli_date(value: date) -> str:
    return value.isoformat()


def parse_cli_date(value: str) -> date:
    """Parse a CLI --start-date/--end-date argument."""

    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"expected YYYY-MM-DD, got {value!r}") from error
