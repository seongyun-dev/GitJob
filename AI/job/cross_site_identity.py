"""One canonical identity for a job posted to both JobKorea and Saramin.

S15P21E102-352. Current Market counts "every valid distinct posting we hold",
and a job advertised on two sites was two postings, so the denominator and
every per-technology count double-counted it.

`job-analysis-input/v1` carries no business number, company id, employment type
or canonical URL, so there is no hard identity to key on. What is left is a
deterministic rule over the fields that do exist. It is deliberately narrow:
every condition must hold, and anything else stays as two postings. Measured on
the published 2026-09-19 population, 223 company+title exact pairs reduced to
94 merges; the other 129 failed one of the guards below and were left alone.

Scope. This is **Current Market only** (`_aggregate_current_market`).
ACTIVE_MATCHING keeps source identity untouched, and so do Raw, analysis_input,
`input_union` observations and the cohort rows themselves -- this module never
rewrites a record, it only answers "which postings should count as one".

Why not fuzzy titles. In the measured data the 0.80-0.90 similarity band mixed
different roles at the same company ("백엔드 개발자" against "백엔드 개발자 리드"),
so a threshold there would merge distinct jobs. Only an exact match after
normalisation counts.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Protocol

__all__ = [
    "MAX_DEADLINE_DELTA_DAYS",
    "canonical_identities",
    "cross_site_candidate_pairs",
    "normalize_company",
    "normalize_title",
    "region_compatible",
]

# Both sites publish the same job with deadlines a day or two apart -- measured
# on 2026-09-19: 131 of 223 exact pairs sat within three days, 39 were more than
# a week apart and read as separate posting cycles. Three days keeps the former
# and drops the latter.
MAX_DEADLINE_DELTA_DAYS = 3
_MARKET_TIMEZONE = timezone(timedelta(hours=9), "Asia/Seoul")

# Legal-form noise only. Nothing here can change which company is meant.
_COMPANY_NOISE = (
    "주식회사",
    "유한회사",
    "유한책임회사",
    "(주)",
    "㈜",
    "(유)",
    "㈜",
    "co.,ltd.",
    "co.,ltd",
    "co.ltd",
    "coltd",
    "ltd.",
    "ltd",
    "inc.",
    "inc",
    "corp.",
    "corp",
    "corporation",
    "company",
    "llc",
)

# Hiring boilerplate that appears on one site and not the other. Role words are
# never listed here: removing one would merge different jobs.
_TITLE_NOISE = (
    "채용공고",
    "채용",
    "모집공고",
    "모집",
    "공고",
    "구인",
    "정규직",
    "계약직",
    "신입",
    "경력",
    "hiring",
    "recruit",
)

_BRACKETED = re.compile(r"[(\[{【<（][^)\]}】>）]*[)\]}】>）]")
_YEAR = re.compile(r"20\d{2}\s*년?")
_NON_WORD = re.compile(r"[^0-9a-z가-힣]+")
_TRAILING_ETC = re.compile(r"\s*외\s*$")


class _Row(Protocol):
    source_site: str
    source_posting_id: str
    company_name: str
    title: str
    region: str | None
    deadline: datetime | None


def normalize_company(name: str | None) -> str:
    """Company name with legal form, spacing, case and width folded away."""

    text = unicodedata.normalize("NFKC", name or "").lower()
    text = _BRACKETED.sub(" ", text)
    for noise in _COMPANY_NOISE:
        text = text.replace(noise, " ")
    return _NON_WORD.sub("", text)


def normalize_title(title: str | None) -> str:
    """Title with hiring boilerplate removed and role tokens preserved."""

    text = unicodedata.normalize("NFKC", title or "").lower()
    text = _BRACKETED.sub(" ", text)
    text = _YEAR.sub(" ", text)
    for noise in _TITLE_NOISE:
        text = text.replace(noise, " ")
    return " ".join(_NON_WORD.sub(" ", text).split())


def region_compatible(left: str | None, right: str | None) -> bool:
    """True when one region is the other, or a narrowing of it.

    Sites disagree on depth for the same office -- "경기 성남시" against
    "경기 성남시 분당구" -- so a prefix relation counts. A missing region is not
    compatible with anything: absence is not agreement.
    """

    if not left or not right:
        return False
    a = _TRAILING_ETC.sub("", left.strip())
    b = _TRAILING_ETC.sub("", right.strip())
    if not a or not b:
        return False
    return a.startswith(b) or b.startswith(a)


def _deadline_close(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return False
    # PostgreSQL timestamptz restores the same instant in the connection's
    # timezone (UTC in production), while collector payloads carry +09:00.
    # The policy is expressed in Korean job-board calendar days, so compare in
    # one explicit timezone instead of letting serialization change a pair.
    left_date = left.astimezone(_MARKET_TIMEZONE).date()
    right_date = right.astimezone(_MARKET_TIMEZONE).date()
    return abs((left_date - right_date).days) <= MAX_DEADLINE_DELTA_DAYS


def _key(row: _Row) -> tuple[str, str]:
    return (row.source_site, row.source_posting_id)


def cross_site_candidate_pairs(
    rows: Iterable[Any],
) -> tuple[tuple[tuple[str, str], tuple[str, str]], ...]:
    """Return every pair that passes the stable cross-site guards.

    Fan-out is intentionally not resolved here. Persisting all guarded pairs
    lets a later selector first remove out-of-scope postings and only then apply
    the one-to-one rule, which is required for Current Market parity.
    """
    by_company: defaultdict[str, defaultdict[str, list[Any]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        company = normalize_company(getattr(row, "company_name", None))
        if not company:
            continue
        by_company[company][getattr(row, "source_site", "")].append(row)

    pairs: set[tuple[tuple[str, str], tuple[str, str]]] = set()
    for sites in by_company.values():
        left_rows = sites.get("JOBKOREA", ())
        right_rows = sites.get("SARAMIN", ())
        if not left_rows or not right_rows:
            continue
        # Candidate pairs first, then drop every posting that has more than one.
        # A repost cycle produces two near-identical postings on one site; there
        # is no evidence saying which one the other site's posting is, so the
        # honest answer is to merge neither.
        candidates: list[tuple[Any, Any]] = []
        for left in left_rows:
            left_title = normalize_title(getattr(left, "title", None))
            if not left_title:
                continue
            for right in right_rows:
                if left_title != normalize_title(getattr(right, "title", None)):
                    continue
                if not _deadline_close(
                    getattr(left, "deadline", None), getattr(right, "deadline", None)
                ):
                    continue
                if not region_compatible(
                    getattr(left, "region", None), getattr(right, "region", None)
                ):
                    continue
                candidates.append((left, right))

        for left, right in candidates:
            pair = tuple(sorted((_key(left), _key(right))))
            pairs.add(pair)
    return tuple(sorted(pairs))


def canonical_identities(rows: Iterable[Any]) -> Mapping[tuple[str, str], str]:
    """Map each posting in a high-confidence one-to-one pair to a shared id."""

    candidates = cross_site_candidate_pairs(rows)
    left_fanout: defaultdict[tuple[str, str], int] = defaultdict(int)
    right_fanout: defaultdict[tuple[str, str], int] = defaultdict(int)
    for left, right in candidates:
        left_fanout[left] += 1
        right_fanout[right] += 1

    mapping: dict[tuple[str, str], str] = {}
    for left, right in candidates:
        if left_fanout[left] != 1 or right_fanout[right] != 1:
            continue
        pair = (left, right)
        # Array framing stays unambiguous when a source posting id contains the
        # ':' or '|' characters that made the old delimiter join collide.
        framed = json.dumps(
            pair, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        digest = sha256(framed).hexdigest()
        canonical = f"xsite-{digest[:32]}"
        mapping[left] = canonical
        mapping[right] = canonical
    return mapping
