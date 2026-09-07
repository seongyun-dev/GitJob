"""Saramin list and detail extraction.

Saramin's search listing is one `div.item_recruit` per posting and carries the
posting id in its own `value` attribute, so rows are located structurally
rather than by scraping the tracking-heavy anchor URLs.

The detail body is `div.user_content` inside `div.jv_cont.jv_detail`. The rest
of the popup is roughly ten times that size — navigation, tracking, related
postings — so narrowing matters here even more than it did on Worknet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from job.collector import ListingRow, PostingDetail
from job.collector.html_tree import HtmlNode, collapse, parse_html

from .dates import parse_deadline, parse_listing_date

__all__ = [
    "SaraminDetail",
    "parse_detail",
    "parse_job_list",
]

_POSTING_ID_RE = re.compile(r"^\d+$")
# `dt`/`dd` pairs in the summary block: 경력, 학력, 근무형태, 자격요건, 우대사항.
_SUMMARY_LABELS = {
    "경력": "career_level",
    "학력": "education",
    "근무형태": "employment_type",
}


@dataclass(frozen=True)
class SaraminDetail(PostingDetail):
    """A Saramin detail page in the shared shape, plus what only Saramin reads.

    Education and employment type are outside the storage scope fixed by
    S15P21E102-99, so they stop here.
    """

    education: str | None = None
    employment_type: str | None = None


def _has_class(node: HtmlNode, name: str) -> bool:
    return name in node.classes


def _first_with_class(root: HtmlNode, tag: str, name: str) -> HtmlNode | None:
    for node in root.iter_descendants():
        if node.tag == tag and _has_class(node, name):
            return node
    return None


def _all_with_class(root: HtmlNode, name: str) -> list[HtmlNode]:
    return [node for node in root.iter_descendants() if _has_class(node, name)]


def _text_of(node: HtmlNode | None) -> str:
    return collapse(node.inner_text()) if node is not None else ""


def parse_job_list(html: str, *, today: date) -> list[ListingRow]:
    """Extract every posting row from a Saramin search page.

    `today` anchors the deadline, which the listing writes without a year.
    """

    root = parse_html(html)
    rows: list[ListingRow] = []
    seen: set[str] = set()

    for item in _all_with_class(root, "item_recruit"):
        posting_id = (item.attrs.get("value") or "").strip()
        if not _POSTING_ID_RE.match(posting_id) or posting_id in seen:
            continue

        title_link = _title_link(item)
        title = _title_of(title_link)
        if not title:
            continue

        listing_date = parse_listing_date(
            _text_of(_first_with_class(item, "span", "job_day"))
        )
        career_level, region = _condition_fields(item)

        rows.append(
            ListingRow(
                source_posting_id=posting_id,
                # Built from the id, not copied from the listing anchor: that
                # href carries search-session tracking parameters that would
                # end up stored in source_url and differ run to run.
                detail_ref=detail_path(posting_id),
                title=title,
                company_name=_text_of(_first_with_class(item, "strong", "corp_name"))
                or None,
                career_level=career_level,
                region=region,
                raw_job_category=_job_sector(item),
                posted_on=listing_date[0] if listing_date else None,
                deadline_label=_text_of(_first_with_class(item, "span", "date"))
                or None,
            )
        )
        seen.add(posting_id)

    return rows


def listing_date_labels(html: str) -> list[str]:
    """Which date label each row used — `등록일` or `수정일`.

    Reported in the run manifest so a run states how many of its postings
    were dated by a modification date rather than a registration date.
    """

    root = parse_html(html)
    labels: list[str] = []
    for item in _all_with_class(root, "item_recruit"):
        parsed = parse_listing_date(
            _text_of(_first_with_class(item, "span", "job_day"))
        )
        if parsed is not None:
            labels.append(parsed[1])
    return labels


def deadline_date_for(row: ListingRow, *, today: date) -> date | None:
    return parse_deadline(row.deadline_label, today=today)


def detail_path(posting_id: str) -> str:
    """The detail path robots.txt allows.

    Saramin's robots.txt disallows `/zf_user/recruit/view/`,
    `/zf_user/recruit/recruit-posting/` and `/recruit/recruit_view.php`, and
    explicitly allows `/zf_user/jobs/view/popup`. The allowed popup serves the
    same 상세요강 body, so this collector uses it and never the disallowed
    paths — see the README.
    """

    return f"/zf_user/jobs/view/popup?rec_idx={posting_id}"


def _title_link(item: HtmlNode) -> HtmlNode | None:
    heading = _first_with_class(item, "h2", "job_tit")
    if heading is None:
        return None
    return heading.find("a")


def _title_of(link: HtmlNode | None) -> str:
    if link is None:
        return ""
    # The `title` attribute holds the unhighlighted title; the link text is
    # broken up by <b> tags wrapping the matched search term.
    attribute = (link.attrs.get("title") or "").strip()
    return attribute or collapse(link.inner_text())


def _condition_fields(item: HtmlNode) -> tuple[str | None, str | None]:
    """Read 경력 and 지역 out of `div.job_condition`.

    The block is a fixed run of spans — 지역, 경력, 학력, 고용형태 — but the
    region span is the one holding links, which is a stronger signal than
    position. Career level is then matched by wording rather than by index, so
    a site that drops the 학력 span does not shift the value silently.
    """

    condition = _first_with_class(item, "div", "job_condition")
    if condition is None:
        return None, None

    region: str | None = None
    career: str | None = None
    for span in condition.find_all("span"):
        text = collapse(span.inner_text())
        if not text:
            continue
        if region is None and span.find("a") is not None:
            region = text
            continue
        if career is None and ("신입" in text or "경력" in text):
            career = text
    return career, region


def _job_sector(item: HtmlNode) -> str | None:
    sector = _first_with_class(item, "div", "job_sector")
    if sector is None:
        return None
    names = [collapse(link.inner_text()) for link in sector.find_all("a")]
    joined = ", ".join(name for name in names if name)
    return joined or None


def _find_detail_scope(root: HtmlNode) -> HtmlNode | None:
    """Narrow to the 상세요강 body.

    Returns None rather than the whole document when the body is absent, so
    the caller records `body_status=PARSE_FAILED` instead of storing a
    popup's worth of navigation as a posting description. Worknet degrades to
    `<body>` because its content region is roughly half the page; here the
    body is under a tenth of it, and that trade does not hold.
    """

    return _first_with_class(root, "div", "user_content")


def parse_detail(html: str, *, today: date) -> SaraminDetail:
    """Extract readable content from a Saramin detail popup."""

    root = parse_html(html)
    body = _find_detail_scope(root)
    description_text = body.inner_text().strip() if body is not None else ""

    summary = _summary_fields(root)
    return SaraminDetail(
        description_text=description_text or None,
        career_level=summary.get("career_level"),
        education=summary.get("education"),
        employment_type=summary.get("employment_type"),
        deadline_label=_detail_deadline_label(root),
        image_sources=_image_sources(body) if body is not None else (),
    )


def _summary_fields(root: HtmlNode) -> dict[str, str]:
    """Read the labelled 경력/학력/근무형태 pairs from the summary block."""

    found: dict[str, str] = {}
    for definition in root.find_all("dl"):
        label = collapse(_text_of(definition.find("dt")))
        key = _SUMMARY_LABELS.get(label)
        if key is None or key in found:
            continue
        value = collapse(_text_of(definition.find("dd")))
        if value:
            found[key] = value
    return found


def _detail_deadline_label(root: HtmlNode) -> str | None:
    """Read the 접수기간 value if the popup states one."""

    for definition in root.find_all("dl"):
        label = collapse(_text_of(definition.find("dt")))
        if label in ("접수기간", "마감일"):
            value = collapse(_text_of(definition.find("dd")))
            if value:
                return value[:60]
    return None


def _image_sources(body: HtmlNode) -> tuple[str, ...]:
    """Image-only postings: collect the body images, skipping site assets."""

    sources: list[str] = []
    for image in body.find_all("img"):
        src = (image.attrs.get("src") or "").strip()
        if not src or "saraminimage.co.kr/common" in src:
            continue
        sources.append(src)
    return tuple(dict.fromkeys(sources))
