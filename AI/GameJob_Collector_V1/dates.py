"""게임잡 date parsing.

The listing writes registration four different ways and none of them carries a
year, so all four need an anchor. Verified against the live listing on
2026-09-08:

    07/28(화) 등록      absolute, no year
    38분 전 등록        relative
    3시간 전 등록       relative
    6일 전 등록         relative

The deadline column adds two more shapes:

    채용시             open-ended; never becomes a date
    ~11/08             no year
    2026.07.15         full date

### Registration and deadline infer the year in opposite directions

A registration date cannot be in the future, so `12/28` seen in January is
last December. A deadline on a live listing is generally ahead, so `01/15`
seen in December is next January. Sharing one inference between them would
silently move a posting a year, which is exactly the class of bug
S15P21E102-148 recorded when a deadline was stored as a registration date.
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
    "parse_detail_timestamps",
    "parse_listing_posted_on",
]

SEOUL = ZoneInfo("Asia/Seoul")

# `07/28(화) 등록`, and the `수정` variant on rows that show no registration
# date. The label is returned so a run can report which one it used.
_LISTING_ABSOLUTE_RE = re.compile(
    r"(?P<mm>\d{1,2})/(?P<dd>\d{1,2})\s*\([^)]*\)\s*(?P<label>등록|수정)"
)
# `38분 전 등록`, `3시간 전 등록`, `6일 전 등록`.
_LISTING_RELATIVE_RE = re.compile(
    r"(?P<amount>\d+)\s*(?P<unit>분|시간|일)\s*전\s*(?P<label>등록|수정)"
)
# The detail page's exact stamps: `2026-07-03 17:07 등록`.
_DETAIL_STAMP_RE = re.compile(
    r"(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\s+"
    r"(?P<hh>\d{1,2}):(?P<mi>\d{2})\s*(?P<label>등록|수정)"
)
# `~11/08` and `~ 11/08(금)`.
_DEADLINE_SHORT_RE = re.compile(r"~\s*(?P<mm>\d{1,2})/(?P<dd>\d{1,2})")
# `2026.07.15`, and `2026-07-15` should the site ever switch separators.
_DEADLINE_FULL_RE = re.compile(r"(?P<y>\d{4})[.\-/](?P<m>\d{1,2})[.\-/](?P<d>\d{1,2})")

_RELATIVE_UNITS = {"분": "minutes", "시간": "hours", "일": "days"}

# Deadlines that never pass. Parsing these as dates would mark an open
# posting CLOSED.
OPEN_ENDED_DEADLINE_LABELS = (
    "채용시",
    "채용시까지",
    "상시채용",
    "상시모집",
    "수시채용",
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
    """Read the listing's registration column, with the label that produced it.

    The label matters for the same reason it did on Saramin: a `수정일` is not
    a registration date, only the best evidence available that the posting was
    in this window. Callers get the label so a run can record which one it
    used instead of presenting one as the other.

    A relative stamp is resolved against `now` and then reduced to a date.
    Precision is not lost in practice — the detail page states the exact
    minute, and `normalize._posted_at_for` prefers it — but a list-only run
    still lands on the right day.
    """

    if not text:
        return None

    relative = _LISTING_RELATIVE_RE.search(text)
    if relative:
        unit = _RELATIVE_UNITS[relative.group("unit")]
        delta = timedelta(**{unit: int(relative.group("amount"))})
        return (now - delta).date(), relative.group("label")

    absolute = _LISTING_ABSOLUTE_RE.search(text)
    if absolute:
        parsed = _with_inferred_year(
            month=int(absolute.group("mm")),
            day=int(absolute.group("dd")),
            today=now.date(),
        )
        if parsed is None:
            return None
        return parsed, absolute.group("label")

    return None


def _with_inferred_year(*, month: int, day: int, today: date) -> date | None:
    """Pick the year for a registration date, which cannot be in the future.

    A day or two of slack absorbs a clock skew between us and the site rather
    than throwing the date back a full year.
    """

    for year in (today.year, today.year - 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if (candidate - today).days <= 1:
            return candidate
    return None


def parse_detail_timestamps(text: str | None) -> dict[str, datetime]:
    """Read the detail page's exact `등록`/`수정` stamps.

    Returned as a mapping keyed by the site's own label, because the caller
    decides which one is the registration date. The site renders these in
    Asia/Seoul with no offset, so the zone is attached here — a naive value
    would be rejected downstream by the contract validator.
    """

    if not text:
        return {}
    found: dict[str, datetime] = {}
    for match in _DETAIL_STAMP_RE.finditer(text):
        label = match.group("label")
        if label in found:
            continue
        try:
            found[label] = datetime(
                int(match.group("y")),
                int(match.group("m")),
                int(match.group("d")),
                int(match.group("hh")),
                int(match.group("mi")),
                tzinfo=SEOUL,
            )
        except ValueError:
            continue
    return found


def is_open_ended_deadline(text: str | None) -> bool:
    if not text:
        return False
    collapsed = "".join(text.split())
    return any(label in collapsed for label in OPEN_ENDED_DEADLINE_LABELS)


def parse_deadline(text: str | None, *, today: date) -> date | None:
    """Read `채용시`, `~MM/DD` or `YYYY.MM.DD` into a date, or None.

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
