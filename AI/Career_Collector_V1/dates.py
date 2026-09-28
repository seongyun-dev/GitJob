"""커리어 date parsing.

Measured against the live listing on 2026-09-09. The registration column
writes itself three ways:

    (2026-07-02 등록)   absolute, **with** year
    (13시간 전 등록)     relative
    (6일 전 등록)        relative

The deadline column adds two:

    상시채용            open-ended; never becomes a date
    ~10/01(목)          no year

The year-bearing absolute form is what separates this site from 게임잡, whose
listing never prints one (`GameJob_Collector_V1/dates.py`). Everything else
here follows that module deliberately — the shapes really are the same, and
two collectors disagreeing about what `~10/01` means would be worse than the
duplication.

### Registration and deadline infer the year in opposite directions

Only the deadline needs inference here, but the rule is written down anyway:
a registration date cannot be in the future, while a deadline on a live
listing is generally ahead. Sharing one inference between them silently moves
a posting by a year — the bug class S15P21E102-148 recorded when a deadline
was stored as a registration date.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

__all__ = [
    "OPEN_ENDED_DEADLINE_LABELS",
    "SEOUL",
    "as_seoul",
    "is_open_ended_deadline",
    "parse_deadline",
    "parse_listing_posted_on",
]

SEOUL = ZoneInfo("Asia/Seoul")

# `(2026-07-02 등록)`. The label is captured so a run can report whether it
# used 등록 or 수정, the same way the other collectors do.
_LISTING_ABSOLUTE_RE = re.compile(
    r"(?P<y>\d{4})[.\-/](?P<m>\d{1,2})[.\-/](?P<d>\d{1,2})\s*(?P<label>등록|수정)"
)
# `(13시간 전 등록)`, `(6일 전 등록)`, and 분 for a posting minutes old.
_LISTING_RELATIVE_RE = re.compile(
    r"(?P<amount>\d+)\s*(?P<unit>분|시간|일)\s*전\s*(?P<label>등록|수정)"
)
# `~10/01(목)` and `~ 10/01`.
_DEADLINE_SHORT_RE = re.compile(r"~\s*(?P<mm>\d{1,2})/(?P<dd>\d{1,2})")
# `2026.10.01`, in case the detail page states a full date.
_DEADLINE_FULL_RE = re.compile(r"(?P<y>\d{4})[.\-/](?P<m>\d{1,2})[.\-/](?P<d>\d{1,2})")

_RELATIVE_UNITS = {"분": "minutes", "시간": "hours", "일": "days"}

# Deadlines that never pass. Parsing these as dates would mark an open
# posting CLOSED. 상시채용 is the most common value on this site's listing —
# 24 of 30 rows on one measured page.
OPEN_ENDED_DEADLINE_LABELS = (
    "상시채용",
    "상시모집",
    "수시채용",
    "채용시",
    "채용시까지",
)

# A posting whose application period has not opened. Not closed, and with no
# usable deadline, so it stays UNKNOWN rather than being guessed.
_NOT_STARTED_LABELS = ("진행예정", "오픈예정")


def as_seoul(value: datetime) -> datetime:
    return value.astimezone(SEOUL)


def parse_listing_posted_on(
    text: str | None,
    *,
    now: datetime,
) -> tuple[date, str] | None:
    """Read the listing's registration cell, with the label that produced it.

    The label matters: a `수정일` is not a registration date, only the best
    evidence available that the posting was in this window. Callers get it so
    a run can record which one it used instead of presenting one as the other.

    The absolute form is tried first. It carries a year, so it needs no
    inference and cannot be moved by a clock difference between us and the
    site — unlike the relative form, which is resolved against `now`.
    """

    if not text:
        return None

    absolute = _LISTING_ABSOLUTE_RE.search(text)
    if absolute:
        try:
            parsed = date(
                int(absolute.group("y")),
                int(absolute.group("m")),
                int(absolute.group("d")),
            )
        except ValueError:
            return None
        return parsed, absolute.group("label")

    relative = _LISTING_RELATIVE_RE.search(text)
    if relative:
        unit = _RELATIVE_UNITS[relative.group("unit")]
        delta = timedelta(**{unit: int(relative.group("amount"))})
        return (now - delta).date(), relative.group("label")

    return None


def is_open_ended_deadline(text: str | None) -> bool:
    if not text:
        return False
    collapsed = "".join(text.split())
    return any(label in collapsed for label in OPEN_ENDED_DEADLINE_LABELS)


def parse_deadline(text: str | None, *, today: date) -> date | None:
    """Read `상시채용`, `~MM/DD` or `YYYY.MM.DD` into a date, or None.

    A short deadline more than a month behind `today` belongs to next year:
    the listing shows live postings, so `~01/15` seen in December is January
    of next year. A month of slack keeps a genuinely just-expired posting in
    the current year instead of pushing it a year out.
    """

    if not text or is_open_ended_deadline(text):
        return None
    if any(label in text for label in _NOT_STARTED_LABELS):
        return None

    full = _DEADLINE_FULL_RE.search(text)
    if full:
        try:
            return date(
                int(full.group("y")), int(full.group("m")), int(full.group("d"))
            )
        except ValueError:
            return None

    short = _DEADLINE_SHORT_RE.search(text)
    if not short:
        return None
    month, day = int(short.group("mm")), int(short.group("dd"))
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if (today - candidate).days <= 31:
            return candidate
    return None
