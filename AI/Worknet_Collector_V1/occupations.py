"""Worknet 직종 codes for the `occupation` search filter (S15P21E102-148).

Collecting without a job filter is not a smaller version of the right
collection — it is the wrong collection. An unfiltered run returned
요양보호사, 가구 제조 and 제조 단순종사원 postings and no software postings at
all, while the site reports roughly 150 new postings an hour across all
occupations, which a twice-daily schedule cannot keep up with.

### Where these codes come from

Worknet publishes no code list on the search page, and the codes are not
한국표준직업분류. They come from the picker's own endpoint, which the search
page's `fn_requestJobSubList` calls:

    POST /wk/l/b/1100/selectJobsSubSearchList.do
    superJobsCd=<parent code>&type=worknet

An empty `superJobsCd` returns the 13 top-level groups; each level returns its
children. Codes are 1-2 characters at level 1, 3 at level 2, and 6 at the leaf.
Re-run that endpoint to refresh this module when Worknet reorganizes.

The `occupation` parameter accepts either level. Level-2 codes are used here:
they are stable, they keep the request short, and a new leaf under a group is
picked up without a code change.

### The filter is a coarse pre-filter, not a classifier

Verified against the live listing on 2026-09-07: `024` returns
"AI 역량이 높은 Back End SW 개발자", "Full-Stack 개발자", "결제플랫폼 앱개발",
and also "제어팀 정규직 구인" and "PMO/PI". Employers choose their own 직종, so
some postings under a software code are not software work. Treat this as
narrowing the candidate set — decide relevance downstream from the collected
posting, not from the filter alone.
"""

from __future__ import annotations

__all__ = [
    "OCCUPATION_GROUPS",
    "OCCUPATION_PRESETS",
    "resolve_occupation_preset",
]

# Level-2 groups that carry development work, with the leaf codes each covers.
# The leaves are recorded for the reader; only the group code is sent.
OCCUPATION_GROUPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "024": (
        "소프트웨어",
        (
            "133100 시스템 소프트웨어 개발자",
            "133101 시스템 소프트웨어 개발자(프로그래머)",
            "133102 펌웨어 및 임베디드 소프트웨어 프로그래머",
            "133200 응용 소프트웨어 개발자",
            "133201 JAVA 프로그래밍 언어 전문가",
            "133202 C언어 및 그 외 프로그래밍 언어 전문가",
            "133203 범용 응용 소프트웨어 프로그래머",
            "133204 산업특화 응용 소프트웨어 프로그래머",
            "133205 네트워크 프로그래머",
            "133206 게임 프로그래머",
            "133207 모바일 애플리케이션 프로그래머",
            "133300 웹 개발자",
            "133301 웹 개발자(웹 엔지니어·웹 프로그래머)",
            "133302 웹 기획자",
            "133900 기타 컴퓨터 시스템 및 소프트웨어 전문가",
        ),
    ),
    "025": (
        "네트워크 시스템 및 정보보안",
        (
            "134100 네트워크 시스템 개발자",
            "134200 정보보안 전문가",
            "134201 정보보호 전문가",
            "134202 침해사고 대응 전문가",
            "134900 기타 네트워크 및 정보 보안 전문가",
        ),
    ),
    "026": (
        "데이터 및 정보시스템·웹 운영",
        (
            "135100 데이터 시스템 전문가",
            "135101 데이터 설계 및 프로그래머",
            "135102 데이터베이스 운영·관리자",
            "135200 데이터 분석가(빅데이터 분석가)",
            "136101 정보시스템 운영자",
            "136102 네트워크 관리자(클라우드 운영관리자)",
            "136103 IT 기술지원 전문가",
            "136200 웹 운영자(홈페이지 관리자)",
        ),
    ),
    "023": (
        "컴퓨터시스템",
        (
            "132000 컴퓨터시스템 전문가",
            "132001 IT 컨설턴트",
            "132002 컴퓨터시스템 설계 및 분석가",
            "132003 IT 감리 전문가(시스템 감리)",
        ),
    ),
    "022": (
        "컴퓨터하드웨어·통신공학",
        (
            "131100 컴퓨터 하드웨어 기술자 및 연구원",
            "131200 통신공학 기술자 및 연구원",
            "131201 통신기기·장비 개발자 및 연구원",
            "131202 통신기술 개발자 및 통신망 운영 기술자",
            "131203 통신공사 감리 기술자",
        ),
    ),
}

# `dev` excludes 022: hardware and telecom engineering is adjacent work whose
# stacks skew the technology counts this collection feeds. It is available as
# `dev-extended` for a run that deliberately wants it.
OCCUPATION_PRESETS: dict[str, tuple[str, ...]] = {
    "software": ("024",),
    "dev": ("024", "025", "026", "023"),
    "dev-extended": ("024", "025", "026", "023", "022"),
}


def resolve_occupation_preset(name: str) -> tuple[str, ...]:
    """Translate a preset name into 직종 codes.

    Raises rather than falling back to "no filter": an unrecognised preset
    must not quietly turn into a full-occupation crawl.
    """

    try:
        return OCCUPATION_PRESETS[name]
    except KeyError:
        known = ", ".join(sorted(OCCUPATION_PRESETS))
        raise ValueError(
            f"unknown occupation preset {name!r}; known presets: {known}"
        ) from None
