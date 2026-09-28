"""Date parsing helpers for JobKorea's human-readable labels."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .parser import clean_text

SEOUL = ZoneInfo("Asia/Seoul")
_RELATIVE_RE = re.compile(r"(?P<count>\d+)\s*(?P<unit>분|시간|일|주)\s*전")
_DATE_RE = re.compile(
    r"(?:(?P<year>20\d{2})[./-])?(?P<month>\d{1,2})[./-](?P<day>\d{1,2})"
)


def as_seoul(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SEOUL)
    return value.astimezone(SEOUL)


def _date_from_match(match: re.Match[str], default_year: int) -> date:
    year = int(match.group("year") or default_year)
    return date(year, int(match.group("month")), int(match.group("day")))


def parse_posted_at(
    label: str | None,
    *,
    now: datetime,
    default_year: int,
) -> datetime | None:
    """Convert labels such as ``3일 전 등록`` and ``08/25(화) 등록``."""

    value = clean_text(label)
    if not value:
        return None
    current = as_seoul(now)

    relative = _RELATIVE_RE.search(value)
    if relative:
        count = int(relative.group("count"))
        unit = relative.group("unit")
        if unit == "분":
            return current - timedelta(minutes=count)
        if unit == "시간":
            return current - timedelta(hours=count)
        if unit == "주":
            return current - timedelta(weeks=count)
        return current - timedelta(days=count)
    if "방금" in value:
        return current
    if "어제" in value:
        return current - timedelta(days=1)
    if "오늘" in value:
        return current

    match = _DATE_RE.search(value)
    if not match:
        return None
    try:
        return datetime.combine(
            _date_from_match(match, default_year),
            time.min,
            tzinfo=SEOUL,
        )
    except ValueError:
        return None


def parse_deadline(
    label: str | None,
    *,
    default_year: int,
) -> datetime | None:
    """Convert a list/detail deadline to Seoul end-of-day time."""

    value = clean_text(label)
    if not value or "상시채용" in value or "채용시마감" in value:
        return None
    match = _DATE_RE.search(value)
    if not match:
        return None
    try:
        return datetime.combine(
            _date_from_match(match, default_year),
            time(23, 59, 59),
            tzinfo=SEOUL,
        )
    except ValueError:
        return None


def date_range_bounds(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    """Return inclusive start and inclusive end converted to a half-open range."""

    if end_date < start_date:
        raise ValueError("end_date must not be before start_date")
    start = datetime.combine(start_date, time.min, tzinfo=SEOUL)
    end_exclusive = datetime.combine(
        end_date + timedelta(days=1),
        time.min,
        tzinfo=SEOUL,
    )
    return start, end_exclusive
