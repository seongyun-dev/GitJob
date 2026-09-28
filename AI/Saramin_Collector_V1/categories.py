"""Saramin 직군 codes for the `cat_kewd` search filter (S15P21E102-148).

An unfiltered search returns 카지노·호텔 공채, 생산기술직 and 생산직 보전반;
`cat_kewd=84` returns 백엔드 개발자 and 클라우드 아키텍트. Verified against
the live search on 2026-09-07, and the parameter comma-joins like Worknet's.

### Where these codes come from

Every posting row on a search page links its own tags as
`/zf_user/jobs/list/job-category?cat_kewd=<code>`, so the code table is read
off a search result rather than from a published list. Re-run a search and
collect those links to refresh this module.

### Why only role codes

`cat_kewd` mixes two kinds of tag in one namespace:

    84  백엔드/서버개발     ← 직무
    235 Java              ← 기술스택

**Only the role codes belong in a preset.** Filtering by stack tags would
bias the measurement this collection feeds: gathering Java-tagged postings and
then counting Java demand is circular. The stack codes are recorded below so
nobody has to rediscover what they are, but no preset uses them.
"""

from __future__ import annotations

__all__ = [
    "CATEGORY_PRESETS",
    "ROLE_CATEGORIES",
    "STACK_CATEGORIES",
    "resolve_category_preset",
]

# Role tags — what the job is.
ROLE_CATEGORIES: dict[str, str] = {
    "84": "백엔드/서버개발",
    "87": "웹개발",
    "92": "프론트엔드",
    "86": "앱개발",
    "2232": "풀스택",
    "167": "S/W",
    "139": "펌웨어",
    "83": "데이터엔지니어",
    "82": "데이터분석가",
    "107": "데이터시각화",
    "181": "AI(인공지능)",
    "856": "AI(인공지능)",
    "108": "딥러닝",
    "131": "챗봇",
    "146": "DevOps",
    "136": "클라우드",
    "142": "API",
    "101": "SI개발",
    "2247": "개발PM",
    "99": "QA/테스터",
    "124": "웹표준·웹접근성",
    "104": "네트워크",
    "98": "IT컨설팅",
    "81": "기술지원",
    "89": "유지보수",
    "138": "트러블슈팅",
    "118": "솔루션",
    "153": "H/W",
}

# Stack tags — what the job uses. Recorded, never used as a filter; see the
# module docstring.
STACK_CATEGORIES: dict[str, str] = {
    "182": "Windows",
    "184": ".NET",
    "193": "AIX",
    "195": "Android",
    "201": "AWS",
    "204": "C#",
    "205": "C++",
    "229": "HTML",
    "234": "iOS",
    "235": "Java",
    "238": "JPA",
    "240": "JSP",
    "241": "Kafka",
    "255": "MSSQL",
    "258": "Node.js",
    "263": "OracleDB",
    "268": "PHP",
    "277": "React",
    "291": "Spring",
}

# `software` is application development only. `dev` adds the data, AI and
# infrastructure roles this analysis treats as development work. `extended`
# adds the support-side roles — network, 기술지원, 유지보수, H/W — which are
# adjacent enough that their stacks would skew the technology counts, so they
# are opt-in.
_SOFTWARE = ("84", "87", "92", "86", "2232", "167", "139")
_DEV_ADDITIONS = (
    "83",
    "82",
    "107",
    "181",
    "856",
    "108",
    "131",
    "146",
    "136",
    "142",
    "101",
    "2247",
    "99",
    "124",
)
_EXTENDED_ADDITIONS = ("104", "98", "81", "89", "138", "118", "153")

CATEGORY_PRESETS: dict[str, tuple[str, ...]] = {
    "software": _SOFTWARE,
    "dev": _SOFTWARE + _DEV_ADDITIONS,
    "dev-extended": _SOFTWARE + _DEV_ADDITIONS + _EXTENDED_ADDITIONS,
}


def resolve_category_preset(name: str) -> tuple[str, ...]:
    """Translate a preset name into 직군 codes.

    Raises rather than falling back to "no filter": an unrecognised preset
    must not quietly turn into a full-site crawl.
    """

    try:
        return CATEGORY_PRESETS[name]
    except KeyError:
        known = ", ".join(sorted(CATEGORY_PRESETS))
        raise ValueError(
            f"unknown category preset {name!r}; known presets: {known}"
        ) from None
