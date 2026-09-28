"""Saramin date parsing.

The listing writes dates in two shortened forms and neither carries a full
year, so both need an anchor:

    등록일 26/09/07     two-digit year
    ~ 10/07(수)         deadline with no year at all
"""

from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

__all__ = [
    "OPEN_ENDED_DEADLINE_LABELS",
    "SEOUL",
    "as_seoul",
    "is_open_ended_deadline",
    "parse_deadline",
    "parse_listing_date",
]

SEOUL = ZoneInfo("Asia/Seoul")

# `등록일 26/09/07`, and `수정일 26/09/07` on postings that show no
# registration date at all — see `parse_listing_date`.
_LISTING_DATE_RE = re.compile(
    r"(?P<label>등록일|수정일)\s*(?P<yy>\d{2})/(?P<mm>\d{1,2})/(?P<dd>\d{1,2})"
)
# `~ 10/07(수)`. The year is absent, so it is inferred in `parse_deadline`.
_DEADLINE_RE = re.compile(r"~?\s*(?P<mm>\d{1,2})/(?P<dd>\d{1,2})")

# Deadlines that never pass. Parsing these as dates would mark an open
# posting CLOSED.
OPEN_ENDED_DEADLINE_LABELS = (
    "채용시",
    "채용시까지",
    "상시채용",
    "상시모집",
    "수시채용",
)

# A posting whose application period has not started yet. It is not closed and
# it has no usable deadline, so it stays UNKNOWN rather than being guessed.
_NOT_STARTED_LABELS = ("진행예정", "예정")


def as_seoul(value: datetime) -> datetime:
    return value.astimezone(SEOUL)


def parse_listing_date(text: str | None) -> tuple[date, str] | None:
    """Read the listing's date column, with the label that produced it.

    The label matters. Roughly a fifth of rows carry `수정일` and no
    `등록일`, and a modification date is not a registration date — it is only
    the best evidence available that the posting was in this window. Callers
    get the label so a run can record which one it used instead of silently
    presenting one as the other.
    """

    if not text:
        return None
    match = _LISTING_DATE_RE.search(text)
    if not match:
        return None
    try:
        parsed = date(
            2000 + int(match.group("yy")),
            int(match.group("mm")),
            int(match.group("dd")),
        )
    except ValueError:
        return None
    return parsed, match.group("label")


def is_open_ended_deadline(text: str | None) -> bool:
    if not text:
        return False
    collapsed = "".join(text.split())
    return any(label in collapsed for label in OPEN_ENDED_DEADLINE_LABELS)


def parse_deadline(text: str | None, *, today: date) -> date | None:
    """Read `~ MM/DD(요일)`, inferring the year from `today`.

    A deadline more than a month behind `today` belongs to next year: the
    listing shows live postings, so `~ 01/15` seen in December is January of
    next year, not eleven months ago. A month of slack keeps a genuinely
    just-expired posting in the current year instead of pushing it a year out.
    """

    if not text or is_open_ended_deadline(text):
        return None
    if any(label in text for label in _NOT_STARTED_LABELS):
        return None
    match = _DEADLINE_RE.search(text)
    if not match:
        return None
    month, day = int(match.group("mm")), int(match.group("dd"))
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if (today - candidate).days <= 31:
            return candidate
    return None
