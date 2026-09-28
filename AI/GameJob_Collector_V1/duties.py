"""게임잡 모집분야 presets for a client-side pre-filter.

Worknet has `occupations.py` and Saramin has `categories.py`, both of which
send a code to the site and let the server filter. **This module cannot do
that**, and the reason is worth recording because it looks like an oversight.

### The site's own duty filter is not reachable by query string

`GI_Total_List.asp` renders ten `duty` checkboxes (1 게임제작, 2 사운드·영상제작,
3 플랫폼 제작, 4 기술지원, 5 게임운영·QA, 6 사업기획, 7 마케팅·미디어,
8 영업·영업관리, 9 경영지원, 10 교육·강의), but they are POSTed into a
server-side session and the listing is then re-rendered from it. Verified on
2026-09-08: `?duty=1`, `?orderTab=3` and `?psTab=40` return a byte-identical
page (364,189 bytes) to the unfiltered request, while `?Page=N` does work. So
the codes are recorded here for whoever revisits this, and the filter runs on
our side instead.

### What it filters on

The listing does not print 모집분야 in `p.info`. The only place a row states
it is the `GA_Application_Prdt` tracking call on the title link, argument 6
(see `parser._listing_job_category`). That is a fragile source, so this
filter is a **request saver, not a correctness boundary**: a row whose
모집분야 cannot be read is *kept*, not dropped, and counted in the manifest.
The value stored on the record comes from the detail page's own 모집분야 row.

The token lists below are the live vocabulary harvested from a full listing
page on 2026-09-08. Matching is substring-based over `·`-normalized text, so
a new sibling token like `게임개발(서버)` matches `게임개발` without an edit.
"""

from __future__ import annotations

__all__ = [
    "DUTY_CODES",
    "DUTY_PRESETS",
    "matches_preset",
    "normalize_duty_text",
    "resolve_duty_preset",
]

# The site's own top-level duty codes. Recorded for reference only — see the
# module docstring for why they are not sent as a request parameter.
DUTY_CODES: dict[str, str] = {
    "1": "게임제작",
    "2": "사운드·영상제작",
    "3": "플랫폼 제작",
    "4": "기술지원",
    "5": "게임운영·QA",
    "6": "사업기획",
    "7": "마케팅·미디어",
    "8": "영업·영업관리",
    "9": "경영지원",
    "10": "교육·강의",
}

# Core engineering. `게임개발` covers the (모바일)/(클라이언트)/(서버) variants.
_SOFTWARE = (
    "게임개발",
    "게임프로그래밍",
    "플랫폼 개발",
    "서버",
    "클라우드",
    "시스템·DB",
    "엔진",
    "게임AI 개발",
    "네트워크",
    "시스템엔지니어링",
    "보안설계",
)

# Development-adjacent engineering work this analysis still treats as
# development: data, QA and the technical PM track.
_DEV_ADDITIONS = (
    "정보·빅데이터 분석",
    "게임운영",
    "개발PM",
    "기술지원",
    "QA",
)

# 기획 and 디자인. Opt-in: 게임기획 is the single most common 모집분야 on the
# site (33 of 40 rows on the sampled page), so including it by default would
# make planning postings dominate the technology counts this collection
# feeds — the same distortion the Saramin and Worknet presets exist to avoid.
_EXTENDED_ADDITIONS = (
    "게임기획",
    "전략기획",
    "인터페이스 디자인",
    "플랫폼 디자인",
)

# Separators that mean the same thing in these labels. The site serves
# U+00B7 as `&#183;`; the others show up in hand-typed 모집분야 values and in
# copies of them pasted into a posting body.
_MIDDLE_DOT_VARIANTS = (
    "ㆍ",  # ㆍ HANGUL LETTER ARAEA
    "・",  # ・ KATAKANA MIDDLE DOT
    "‧",  # ‧ HYPHENATION POINT
    "•",  # • BULLET
)

DUTY_PRESETS: dict[str, tuple[str, ...]] = {
    "software": _SOFTWARE,
    "dev": _SOFTWARE + _DEV_ADDITIONS,
    "dev-extended": _SOFTWARE + _DEV_ADDITIONS + _EXTENDED_ADDITIONS,
}


def normalize_duty_text(value: str | None) -> str:
    """Fold the separators the site mixes into one comparable form.

    The listing writes `·` as the entity `&#183;` and the detail page writes
    the character, and both pad around commas inconsistently. Whitespace is
    removed entirely rather than collapsed, so `플랫폼 개발` matches
    `플랫폼개발`.
    """

    if not value:
        return ""
    folded = value
    for variant in _MIDDLE_DOT_VARIANTS:
        folded = folded.replace(variant, "·")
    return "".join(folded.split()).lower()


def resolve_duty_preset(name: str) -> tuple[str, ...]:
    """Translate a preset name into 모집분야 tokens.

    Raises rather than falling back to "no filter": an unrecognised preset
    must not quietly turn into a full-site crawl.
    """

    try:
        return DUTY_PRESETS[name]
    except KeyError:
        known = ", ".join(sorted(DUTY_PRESETS))
        raise ValueError(
            f"unknown duty preset {name!r}; known presets: {known}"
        ) from None


def matches_preset(
    job_category: str | None,
    tokens: tuple[str, ...],
) -> bool | None:
    """Does this 모집분야 fall in the preset?

    Returns None when there is nothing to judge — no 모집분야 was readable on
    the row. The caller keeps such a row and counts it, because a silently
    dropped posting can never be collected again, while an extra detail fetch
    only costs a request.
    """

    normalized = normalize_duty_text(job_category)
    if not normalized:
        return None
    return any(normalize_duty_text(token) in normalized for token in tokens)
