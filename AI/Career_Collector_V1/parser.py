"""커리어 HTML parsing.

Measured against `job.career.co.kr` on 2026-09-09.

### The listing is a table, and the ad slots are not rows

A search page carries far more `/recruit/view/` links than postings: 68 links
on page 1 against 30 actual rows, and 2 links on page 9 against **none**. The
extra links are banner and sidebar slots, and they rotate, so a run that
counted links would never see the listing end — pages 9 through 12 each
served one or two "new" ids forever.

Taking only `<tr>` elements with at least five `<td>` children and a detail
link removes them completely. Page 9 then parses as zero rows, which is how
this collector knows the listing is exhausted. Measured: H0 ends at page 8
with 227 postings; N0 was still serving rows at page 12.

### Cells are read by content, not by position

The five columns are 회사명 / 채용제목 / 지원자격 / 근무조건 / 마감일·등록일,
and the last three hold two `span.itx` values each with no distinguishing
class between them. 지원자격 is 경력 then 학력; 근무조건 is 고용형태 then
지역. Reading the second span of 근무조건 as the region works today and breaks
the day a column gains a value, so each value is identified by what it says:
an employment type against a known list, a career level by its own wording.

### The site's 직종 tags are the employer's, and they are broad

`span.otNm` carries up to seven tags per posting. One measured Product Owner
posting was tagged 웹프로그래머, 응용프로그래머 **and** 서버.보안.네트워크.DB.
They are kept in `raw_job_category` because the contract has a place for the
site's own category text, but they are not usable as a filter — the
server-side `i_jc1` 대분류 is what narrows the run. See the crawler.

### 시작일 is not 등록일

The detail page states `시작일 2026.07.02 13:00`, which is the application
window opening, and on the measured posting it happened to equal the listing's
`(2026-07-02 등록)`. It is still a different field, and
`job.collector.normalize._posted_at_for` prefers a detail timestamp over the
listing column — so promoting 시작일 to `posted_at` would store an application
date as a registration date for every posting scheduled ahead of time. That is
the exact failure S15P21E102-148 recorded. `parse_detail` therefore returns no
`posted_at`, and the labelled listing column stands.

### The body is `jp_content`, and only `jp_content`

The posting body sits in `div.jp_content`. Inside it are `role_desc`,
`etc_desc`, `org_desc` and `notice_desc`, which look like section containers
and are not: they repeat (three `role_desc` on one page), they nest inside
`jp_content`, and their names do not match their contents — one measured
`role_desc` held "보상 연봉 : ...". They are class names from the employer's
own HTML template. Reading them as sections would double the body text and
label it wrongly, so the parser takes the one container that holds all of it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime

from job.collector import ListingRow, PostingDetail
from job.collector.html_tree import HtmlNode, collapse, parse_html

from .dates import is_open_ended_deadline, parse_listing_posted_on

__all__ = [
    "DETAIL_PATH_PREFIX",
    "listing_date_labels",
    "parse_detail",
    "parse_job_list",
    "posting_id_from_ref",
]

DETAIL_PATH_PREFIX = "/recruit/view/"

_DETAIL_ID_RE = re.compile(r"/recruit/view/(\d+)")

# 근무조건 holds a 고용형태 and a 지역 with the same class. This set decides
# which is which; anything not in it is treated as the region.
_EMPLOYMENT_TYPES = (
    "정규직",
    "계약직",
    "인턴직",
    "인턴",
    "아르바이트",
    "파견직",
    "위촉직",
    "프리랜서",
    "병역특례",
    "시간제",
    "연수생",
    "일용직",
    "교육생",
    "파트타임",
    "위탁계약직",
)

# 지원자격 holds a 경력 and a 학력. Only the career level is in scope — the
# interface docstring keeps education out of the contract entirely.
_CAREER_MARKERS = ("경력", "신입", "무관")
_EDUCATION_MARKERS = ("학력", "고졸", "대졸", "초대졸", "석사", "박사")

# `div.rcInfCont` and `div.clst` both render a label as `span.lb` followed by
# the value. The value tag differs between them (`span.vl` vs `div.po`), so
# the label's siblings are read rather than a fixed tag.
_LABEL_CLASS = "lb"

_BODY_CONTAINER_CLASS = "jp_content"
# Tried in order when `jp_content` is absent, which is what a restructured or
# minimal posting looks like.
_BODY_FALLBACK_CLASSES = ("rcvCirCont", "recViewArea")


def posting_id_from_ref(ref: str) -> str | None:
    match = _DETAIL_ID_RE.search(ref or "")
    return match.group(1) if match else None


def _detail_link(row: HtmlNode) -> HtmlNode | None:
    for anchor in row.find_all("a"):
        if DETAIL_PATH_PREFIX in anchor.attrs.get("href", ""):
            return anchor
    return None


def _listing_rows(html: str) -> list[tuple[HtmlNode, list[HtmlNode], HtmlNode]]:
    """Table rows that are actually postings, with their cells and link."""

    root = parse_html(html)
    found: list[tuple[HtmlNode, list[HtmlNode], HtmlNode]] = []
    for row in root.find_all("tr"):
        cells = [child for child in row.children if child.tag == "td"]
        if len(cells) < 5:
            continue
        link = _detail_link(row)
        if link is None:
            continue
        found.append((row, cells, link))
    return found


def _texts(cell: HtmlNode, css_class: str) -> list[str]:
    out: list[str] = []
    for node in cell.iter_descendants():
        if css_class in node.classes:
            text = collapse(node.inner_text())
            if text:
                out.append(text)
    return out


def _first_class_text(cell: HtmlNode, css_class: str) -> str | None:
    values = _texts(cell, css_class)
    return values[0] if values else None


def _career_level(cell: HtmlNode) -> str | None:
    for value in _texts(cell, "itx"):
        if any(marker in value for marker in _EDUCATION_MARKERS):
            continue
        if any(marker in value for marker in _CAREER_MARKERS):
            return value
    return None


def _region(cell: HtmlNode) -> str | None:
    for value in _texts(cell, "itx"):
        if value in _EMPLOYMENT_TYPES:
            continue
        # A compound like "정규직/계약직" or "정규직, 프리랜서, 계약직" is still
        # an employment type. Each part is stripped before matching: the
        # comma-separated form arrives with a space after the separator, and
        # without the strip the whole value fell through and was stored as the
        # region.
        parts = [part.strip() for part in re.split(r"[/,·]", value)]
        if parts and all(part in _EMPLOYMENT_TYPES for part in parts if part):
            continue
        return value
    return None


def _deadline_and_registration(
    cell: HtmlNode,
    *,
    now: datetime,
) -> tuple[str | None, tuple[str, str] | None]:
    """Split the last column into a deadline label and a registration date.

    Both live in `span.itx` with only a utility class between them, and a
    recently posted row puts a relative registration stamp
    ("(13시간 전 등록)") where an older row puts the deadline. Each value is
    therefore classified by what it parses as.
    """

    deadline: str | None = None
    registration: tuple[str, str] | None = None

    for value in _texts(cell, "itx"):
        parsed = parse_listing_posted_on(value, now=now)
        if parsed is not None:
            if registration is None:
                registration = parsed
            continue
        if deadline is None and (
            is_open_ended_deadline(value) or "~" in value or "/" in value
        ):
            deadline = value
    return deadline, registration


def parse_job_list(html: str, *, now: datetime) -> Sequence[ListingRow]:
    """Extract listing rows. Returns empty for a page past the last one."""

    rows: list[ListingRow] = []
    for _row, cells, link in _listing_rows(html):
        ref = link.attrs.get("href", "")
        posting_id = posting_id_from_ref(ref)
        title = collapse(link.inner_text())
        if not posting_id or not title:
            continue

        deadline_label, registration = _deadline_and_registration(cells[4], now=now)
        categories = _texts(cells[1], "otNm")

        rows.append(
            ListingRow(
                source_posting_id=posting_id,
                detail_ref=ref,
                title=title,
                company_name=_first_class_text(cells[0], "tx"),
                career_level=_career_level(cells[2]),
                region=_region(cells[3]),
                # Kept as the site wrote them, `#` and all, so a downstream
                # reader can tell a site tag from our own classification.
                raw_job_category=" ".join(categories) or None,
                posted_on=registration[0] if registration else None,
                deadline_label=deadline_label,
            )
        )
    return rows


def listing_date_labels(html: str, *, now: datetime) -> list[str]:
    """The 등록/수정 labels the page used, for the run manifest.

    A row dated by its modification date is not wrong to collect, but a run
    should be able to say how many of those there were.
    """

    labels: list[str] = []
    for _row, cells, _link in _listing_rows(html):
        _deadline, registration = _deadline_and_registration(cells[4], now=now)
        if registration is not None:
            labels.append(registration[1])
    return labels


def _labelled_values(root: HtmlNode) -> dict[str, str]:
    """Read every `span.lb` label with the value rendered beside it.

    `rcInfCont` wraps values in `span.vl` and `clst` uses `div.po`, so the
    value is taken as the label's parent text minus the label itself rather
    than by looking for a fixed tag.
    """

    found: dict[str, str] = {}
    for node in root.iter_descendants():
        if _LABEL_CLASS not in node.classes:
            continue
        label = collapse(node.inner_text())
        if not label or label in found:
            continue
        parent = node.parent
        if parent is None:
            continue
        whole = collapse(parent.inner_text())
        if not whole.startswith(label):
            continue
        value = whole[len(label) :].strip()
        if value:
            found[label] = value
    return found


def _body_text_and_images(root: HtmlNode) -> tuple[str | None, tuple[str, ...]]:
    for css_class in (_BODY_CONTAINER_CLASS, *_BODY_FALLBACK_CLASSES):
        for node in root.iter_descendants():
            if css_class not in node.classes:
                continue
            text = node.inner_text().strip()
            images = tuple(
                dict.fromkeys(
                    src
                    for img in node.find_all("img")
                    if (src := img.attrs.get("src", "").strip())
                )
            )
            if text or images:
                return (text or None), images
    return None, ()


def parse_detail(html: str) -> PostingDetail:
    """Extract one detail page. Must not raise on unexpected markup."""

    root = parse_html(html)
    labels = _labelled_values(root)
    description_text, images = _body_text_and_images(root)

    region = labels.get("근무지역")
    if region:
        # "서울 관악구 지도보기" — the map button sits inside the value cell.
        region = re.sub(r"\s*지도보기\s*$", "", region).strip() or None

    deadline_label = labels.get("마감일") or labels.get("접수기간")

    return PostingDetail(
        description_text=description_text,
        career_level=labels.get("경력"),
        region=region,
        raw_job_category=None,
        # Deliberately absent. See the module docstring: 시작일 is the
        # application window opening, not the registration date, and the
        # normalizer would prefer it over the labelled listing column.
        posted_at=None,
        deadline_label=deadline_label,
        image_sources=images,
        section_names=tuple(labels),
    )
