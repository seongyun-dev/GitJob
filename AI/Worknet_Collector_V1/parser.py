"""Worknet list and detail extraction.

Extraction is driven by link shape and labelled text rather than CSS class
names. Worknet's markup carries generated class names that change between
deployments, while the detail-link query string (`wantedAuthNo`) and the
Korean field labels are stable and are what the site actually guarantees.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from job.collector import ListingRow, PostingDetail

from .dates import is_open_ended_deadline, parse_date, parse_datetime
from .html_tree import HtmlNode, ancestor_row, collapse, parse_html

DETAIL_PATH = "/wk/a/b/1500/empDetailAuthView.do"

_POSTING_ID_RE = re.compile(r"wantedAuthNo=([A-Za-z0-9]+)", re.IGNORECASE)
_DETAIL_HREF_RE = re.compile(r"empDetailAuthView\.do", re.IGNORECASE)

# Korean administrative prefixes, longest first so 특별자치시 wins over 시.
_REGION_RE = re.compile(
    r"("
    r"서울특별시|부산광역시|대구광역시|인천광역시|광주광역시|대전광역시|울산광역시|"
    r"세종특별자치시|제주특별자치도|강원특별자치도|전북특별자치도|"
    r"경기도|충청북도|충청남도|전라남도|경상북도|경상남도|충북|충남|전남|경북|경남|강원|전북|제주"
    r")"
    r"(?:\s+\S+)?"
)
_CAREER_RE = re.compile(
    r"(경력무관|신입·경력|신입/경력|신입|경력\s*\d+년?\s*이상|경력)"
)
_EDUCATION_RE = re.compile(
    r"(학력무관|고졸|대졸\(2,3년\)|대졸\(4년\)|대학원|초대졸|석사|박사)"
)
_EMPLOYMENT_RE = re.compile(
    r"(기간의 정함이 없는 근로계약|기간의 정함이 있는 근로계약|정규직|계약직|"
    r"파견근로|인턴|일용|시간(?:제)?)"
)
# The listing labels this column "등록일" while the detail page uses
# "등록일시". Accepting the suffix is what makes the detail page parse at
# all. The value class keeps ":" so a clock time (2026.09.07 10:53:54) is
# captured with the date instead of being cut at the first colon.
_REG_DATE_LABEL_RE = re.compile(
    r"등록일(?:시|자)?\s*[:：]?\s*([0-9]{4}\s*[./-]\s*[0-9.\-/: ]+)"
)
# A date must follow the label. Worknet also writes "마감일까지" *after* an
# application-period range ("접수 기간 ... ~ ... 마감일까지"), and there an
# open capture returned "까지 채용사이트 바로가기 ..." as the label. That
# parsed to no date, so the posting was stored with posting_status=UNKNOWN.
_CLO_DATE_LABEL_RE = re.compile(
    r"마감일\s*[:：]?\s*(20\d{2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{1,2}[^\n|]{0,16})"
)
# The other form Worknet uses: an application period whose end is the
# deadline. Bounded so a missing "~" cannot swallow the document.
_APPLY_PERIOD_RE = re.compile(r"접수\s*기간\s*([^\n|]{0,60})")
_DATE_TOKEN_RE = re.compile(r"20\d{2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{1,2}")

# Closes the in-page header block on both observed detail templates.
_VIEW_COUNT_RE = re.compile(r"^조회수\s*[\d,]+$")
# The header sits at the top of the region; searching further would let a
# view counter elsewhere on the page cut real content.
_HEADER_SEARCH_LIMIT = 30

# Detail-page section headings observed on Worknet postings.
DETAIL_SECTIONS = (
    "모집요강",
    "근무조건",
    "우대사항",
    "복리후생",
    "전형방법",
    "기업정보",
)
_SECTION_RE = re.compile("|".join(re.escape(name) for name in DETAIL_SECTIONS))


# Worknet listing rows carry nothing Worknet-specific, so the shared shape
# from S15P21E102-99 is used directly rather than re-declared here.


@dataclass(frozen=True)
class DetailContent(PostingDetail):
    """A Worknet detail page in the shared shape, plus what only Worknet reads.

    Education and employment type are outside the storage scope fixed by
    S15P21E102-99, so they stay on this subclass: the parser may read them for
    its own filtering, but nothing downstream of `normalize_posting` sees them.
    """

    education: str | None = None
    employment_type: str | None = None


def posting_id_from_href(href: str) -> str | None:
    match = _POSTING_ID_RE.search(href)
    return match.group(1) if match else None


def _is_detail_link(node: HtmlNode) -> bool:
    href = node.attrs.get("href", "")
    return bool(_DETAIL_HREF_RE.search(href)) and posting_id_from_href(href) is not None


def _company_from_row(row: HtmlNode, detail_link: HtmlNode) -> str:
    """Company name is a sibling link that does not point at the posting."""

    for anchor in row.find_all("a"):
        if anchor is detail_link or _is_detail_link(anchor):
            continue
        label = collapse(anchor.inner_text()).strip("[]() ")
        if label:
            return label

    cells = row.find_all("td")
    if cells:
        first = collapse(cells[0].inner_text()).strip("[]() ")
        if first:
            return first
    return ""


def _row_text(row: HtmlNode) -> str:
    return collapse(row.inner_text())


def _career_from_text(text: str) -> str | None:
    match = _CAREER_RE.search(text)
    return match.group(1) if match else None


def _region_from_text(text: str) -> str | None:
    match = _REGION_RE.search(text)
    if match is None:
        return None
    return collapse(match.group(0))


_DETAIL_FIELD_LABELS = frozenset(
    {
        "모집직종",
        "모집인원",
        "경력",
        "경력조건",
        "학력",
        "고용형태",
        "근무예정지",
        "근무지역",
        "근무지",
        "지역",
        "임금",
        "임금조건",
        "급여",
        "채용직급",
        "우대조건",
        "근무형태",
        "근무시간",
        "사회보험",
        "퇴직금지급방법",
        "인근전철역",
        "지도보기",
        "길찾기",
        "접수기간",
        "접수방법",
        "제출서류준비물",
        *(name.replace(" ", "") for name in DETAIL_SECTIONS),
    }
)


def _field_key(text: str) -> str:
    return re.sub(r"\s+", "", text).rstrip(":：")


def _detail_field(text: str, labels: frozenset[str]) -> tuple[bool, str | None]:
    """Read standalone/colon-labelled values, never caption or company text."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if _field_key(line) == "기업정보":
            # A contiguous tab strip repeats 모집요강 before actual job fields.
            # Only that observed navigation shape may cross the company boundary.
            tail = lines[index + 1 : index + 3]
            is_tab = (
                index > 0
                and lines[index - 1] == "전형방법"
                and (tail[:1] == ["모집요강"] or tail == ["추천정보", "모집요강"])
            )
            if not is_tab:
                break
        label, separator, inline = line.replace("：", ":").partition(":")
        if _field_key(label) not in labels:
            continue
        parts = [inline.strip()] if separator and inline.strip() else []
        for following in lines[index + 1 :]:
            key = _field_key(following.split(":", 1)[0].split("：", 1)[0])
            # '경력' can itself be a value, including after '신입 ,'.
            if key in _DETAIL_FIELD_LABELS and key not in labels:
                break
            parts.append(following)
        value = collapse(" ".join(parts))
        return True, value if value and value not in {
            "-",
            "미기재",
            "해당없음",
        } else None
    return False, None


def _condition_text(text: str) -> str:
    """Legacy unlabelled prose is usable only inside the working-conditions section."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "근무조건":
            parts = []
            for following in lines[index + 1 :]:
                if following.strip() in DETAIL_SECTIONS:
                    break
                if "제공" not in following or "표" not in following:
                    parts.append(following)
            return collapse(" ".join(parts))
    return ""


def _detail_job_category(text: str) -> str | None:
    """Read the 모집직종 value, which is the only job-category field Worknet labels.

    Every other collector fills `raw_job_category` from a site category field, and
    `job.cohort._matches_role` splits that value on `[,;|]` before comparing each
    token to the role aliases. Worknet publishes the same kind of value —
    `펌웨어(Firmware),회로설계` on the 2026-09-13 sample — under 모집직종, so the
    shared slot was simply left unfilled rather than being unavailable here.

    The label already belongs to `_DETAIL_FIELD_LABELS`, so the table caption that
    repeats every label on one line does not match and the value stops at 모집인원.
    """
    _, value = _detail_field(text, frozenset({"모집직종"}))
    return value


def _detail_filters(text: str) -> tuple[str | None, str | None]:
    has_career, career = _detail_field(text, frozenset({"경력", "경력조건"}))
    has_region, region = _detail_field(
        text, frozenset({"근무예정지", "근무지역", "근무지", "지역"})
    )
    fallback = _condition_text(text)
    if not has_career:
        career = _career_from_text(fallback)
    elif career and _field_key(career) in {"관계없음", "무관", "경력관계없음"}:
        career = "경력무관"
    if not has_region:
        region = _region_from_text(fallback)
    return career, region


def _posted_on_from_row(text: str) -> date | None:
    labelled = _REG_DATE_LABEL_RE.search(text)
    if labelled:
        parsed = parse_date(labelled.group(1))
        if parsed is not None:
            return parsed
    tokens = _DATE_TOKEN_RE.findall(text)
    if tokens:
        return parse_date(tokens[0])
    return None


def _deadline_label_from_row(text: str) -> str | None:
    """Read a deadline from a listing row or a detail body.

    Worknet presents it two ways and only the first was handled, which left
    5 of 8 postings in a live run with no deadline, and therefore with
    posting_status=UNKNOWN:

        접수 마감일 2026.09.18 (금) 24:00              labelled
        접수 기간 2026.09.07 ~ 2026.09.13 마감일까지    period
    """

    labelled = _CLO_DATE_LABEL_RE.search(text)
    if labelled:
        label = collapse(labelled.group(1))
        if label:
            return label
    period = _APPLY_PERIOD_RE.search(text)
    if period:
        # The end of the period is the deadline; its start is not.
        period_dates = _DATE_TOKEN_RE.findall(period.group(1))
        if len(period_dates) >= 2:
            return collapse(period_dates[-1])
    if is_open_ended_deadline(text):
        return "채용시까지"
    tokens = _DATE_TOKEN_RE.findall(text)
    if len(tokens) >= 2:
        return collapse(tokens[1])
    return None


def parse_job_list(html: str) -> list[ListingRow]:
    """Extract every posting row from a Worknet listing page.

    Rows are found through their detail link, so listing layout changes that
    keep the link shape do not break collection. Rows without a usable
    posting id or title are skipped rather than emitted half-filled.
    """

    root = parse_html(html)
    items: list[ListingRow] = []
    seen: set[str] = set()

    for anchor in root.find_all("a"):
        if not _is_detail_link(anchor):
            continue
        href = anchor.attrs.get("href", "")
        posting_id = posting_id_from_href(href)
        if posting_id is None or posting_id in seen:
            continue

        title = collapse(anchor.inner_text())
        if not title:
            continue

        row = ancestor_row(anchor)
        scope = row if row is not None else (anchor.parent or anchor)
        text = _row_text(scope)

        items.append(
            ListingRow(
                source_posting_id=posting_id,
                detail_ref=href,
                title=title,
                company_name=_company_from_row(scope, anchor),
                career_level=_career_from_text(text),
                region=_region_from_text(text),
                posted_on=_posted_on_from_row(text),
                deadline_label=_deadline_label_from_row(text),
            )
        )
        seen.add(posting_id)

    return items


def _image_sources(root: HtmlNode) -> tuple[str, ...]:
    """Posting-body images, used to tell an image-only body apart."""

    sources: list[str] = []
    for image in root.find_all("img"):
        src = image.attrs.get("src", "").strip()
        if not src or src.startswith("data:"):
            continue
        # Chrome/site furniture rather than posting content.
        if "/static/images/" in src or "/logo/" in src:
            continue
        if src not in sources:
            sources.append(src)
    return tuple(sources)


_DETAIL_SCOPE_SELECTORS: tuple[tuple[str, str, str], ...] = (
    ("div", "class", "cont_wrap_area"),
    ("div", "id", "contents"),
    ("section", "id", "container"),
)


def _find_detail_scope(root: HtmlNode) -> HtmlNode:
    """Narrow to the posting content region.

    The full `<body>` is roughly half site chrome — global header, GNB,
    breadcrumb, footer and system notices. Measured on a live posting it was
    7,737 characters against 3,645 for the content region, so taking the whole
    body would hand downstream technology extraction thousands of characters
    of navigation text to match against.

    Selectors are tried narrowest first and fall back to the body, so a layout
    change degrades to the old behaviour instead of losing the posting.
    """

    body = root.find("body") or root
    for tag, attr, value in _DETAIL_SCOPE_SELECTORS:
        for node in body.iter_descendants():
            if node.tag != tag:
                continue
            if attr == "id" and node.attrs.get("id") == value:
                return node
            if attr == "class" and value in node.classes:
                return node
    return body


def _strip_page_header(text: str) -> str:
    """Drop the in-page header that survives the container narrowing.

    `_find_detail_scope` removes the site's global chrome, but inside the
    content region Worknet still opens with page furniture, and both observed
    templates end that block with a view counter:

        채용정보 상세 / 링크 복사 / 이메일 전송 / 인쇄하기 /
        채용정보 / 기업정보 / (주)코넥신 / <공고 제목> / 조회수 27

    Leaving it in cost more than a few wasted characters. Technology
    extraction looks back a few lines for a section heading, and a company
    name containing "기술" was picked up as the section for a real mention —
    `위쉬정보기술㈜` was reported where `자격요건` belonged.

    The 민간연계 template then repeats every section name as a tab strip
    before the content starts. That block is dropped only when it is a solid
    run of section names ending in a repeat, so a posting that genuinely
    carries two `모집요강` blocks keeps both.

    Every step degrades to "return what we had" rather than risk emptying a
    posting body.
    """

    lines = text.split("\n")
    stripped = [line.strip() for line in lines]

    start = 0
    for index, line in enumerate(stripped[:_HEADER_SEARCH_LIMIT]):
        if _VIEW_COUNT_RE.match(line):
            start = index + 1
            break

    remainder = lines[start:]
    tail = stripped[start:]

    first = next(
        (index for index, line in enumerate(tail) if line in DETAIL_SECTIONS),
        None,
    )
    if first is not None:
        repeat = next(
            (
                index
                for index in range(first + 1, len(tail))
                if tail[index] == tail[first]
            ),
            None,
        )
        # Only a tab strip: between the first heading and the repeat there is
        # nothing but section names and blank lines — no content.
        if repeat is not None and all(
            not line or line in DETAIL_SECTIONS for line in tail[first:repeat]
        ):
            remainder = remainder[repeat:]

    trimmed = "\n".join(remainder)
    return trimmed if trimmed.strip() else text


def parse_detail(html: str) -> DetailContent:
    """Extract readable content from a Worknet detail page."""

    root = parse_html(html)
    body = _find_detail_scope(root)
    description_text = _strip_page_header(body.inner_text())
    flat = collapse(description_text)

    # Only a labelled value counts. Guessing the first date anywhere in a
    # 3,600-character body invented registration dates: on a live posting it
    # picked up the deadline (2026.10.30) and reported it as the posting
    # date. A missing value stays None so the caller falls back to the
    # listing column, which is labelled and reliable.
    posted_at = None
    labelled = _REG_DATE_LABEL_RE.search(flat)
    if labelled:
        posted_at = parse_datetime(labelled.group(1))

    education = _EDUCATION_RE.search(flat)
    employment = _EMPLOYMENT_RE.search(flat)
    career, region = _detail_filters(description_text)
    raw_job_category = _detail_job_category(description_text)

    return DetailContent(
        description_text=description_text,
        section_names=tuple(dict.fromkeys(_SECTION_RE.findall(flat))),
        career_level=career,
        region=region,
        raw_job_category=raw_job_category,
        education=education.group(1) if education else None,
        employment_type=employment.group(1) if employment else None,
        posted_at=posted_at,
        deadline_label=_deadline_label_from_row(flat),
        image_sources=_image_sources(body),
    )
