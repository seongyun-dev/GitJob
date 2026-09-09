"""게임잡 list and detail extraction.

The listing is a plain table: one `tr` per posting, with the posting id in the
title link's `GI_No` query parameter. The detail page is newer markup — a run
of `dl.recruit-data-item` label/value pairs over `dt`/`dd`, and the posting
body in `div.job-sub-section__body`.

### The body is in iframes, so parsing it takes a second request

`div.job-sub-section__body` does not contain the 담당업무 or 자격조건 text. It
contains an `iframe` per section:

    담당업무  /Recruit/GI_Read_Comt_Ifrm?gno={id}
    자격조건  /Recruit/GI_Read_GI_Comment_Ifrm?gno={id}

So one posting costs up to three requests, and `parse_detail` cannot return a
`description_text` on its own. The crawler fetches the fragments and calls
`parse_body_fragment`; `body_iframe_refs` reads the srcs out of the page
rather than hardcoding them, so a renamed endpoint degrades to "no body"
(`body_status=PARSE_FAILED`) instead of silently fetching the wrong thing.

### 키워드 is deliberately not turned into technology mentions

The detail page carries a `키워드` row that is exactly what this project wants
— `서버, MS-SQL, 네트워크, Unreal, Unity, 게임프로그래밍`. It still stops at
this dataclass. `job.contracts.SourceSurface` is `TITLE | BODY`, so a mention
harvested from a site's own tag list has no surface to be recorded under, and
storing it as `BODY` would claim the posting body said something it did not.
Promoting it needs a contract change (a `SITE_TAG` surface), which is
S15P21E102-90's call and not this collector's. The count is reported in the
run manifest so the value of making that change is visible.
"""

from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass
from datetime import date, datetime

from job.collector import ListingRow, PostingDetail
from job.collector.html_tree import HtmlNode, collapse, parse_html

from .dates import parse_detail_timestamps, parse_listing_posted_on

__all__ = [
    "GameJobDetail",
    "body_iframe_refs",
    "detail_path",
    "listing_date_labels",
    "parse_body_fragment",
    "parse_detail",
    "parse_job_list",
]

_POSTING_ID_RE = re.compile(r"[?&]GI_No=(\d+)", re.IGNORECASE)
# The listing states 모집분야 in exactly one place: the tracking call on the
# title link wraps it, the 게임분야 and the 지역 in `IsNullOrWhiteSpace(...)`,
# in that order. Verified stable across all 40 rows of a listing page on
# 2026-09-08. Only the first is read, and a miss is reported as "unknown"
# rather than guessed — see `duties.matches_preset`.
_TRACKING_ARG_RE = re.compile(r"IsNullOrWhiteSpace\('((?:[^']|\\')*)'\)")

# Label rows on the detail page. 학력 and 직급/직책 are read for the manifest
# and for a site-side sanity check only: S15P21E102-99 puts education outside
# the storage scope, so they stop at `GameJobDetail`.
_SUMMARY_LABELS = {
    "모집분야": "raw_job_category",
    "키워드": "keywords",
    "경력": "career_level",
    "고용형태": "employment_type",
    "학력": "education",
    "마감일": "deadline_label",
    "급여": "salary",
    "모집인원": "headcount",
    "게임분야": "game_field",
}

# Sections that are not part of the posting. 기업정보 and 기업뉴스 are the
# employer's profile and press, rendered in the same section markup; folding
# them into `description_text` would put company boilerplate into every
# posting body and into the content hash.
_NON_POSTING_SECTIONS = ("기업정보", "기업뉴스", "관련공고", "추천공고")

# Site chrome and spacers served from the asset host, not posting artwork.
_ASSET_HOST_MARKERS = ("/pc/images/", "/mo/images/", "/common/", "blank.gif")


@dataclass(frozen=True)
class GameJobDetail(PostingDetail):
    """A 게임잡 detail page in the shared shape, plus what only 게임잡 states.

    Everything added here is outside the storage scope fixed by
    S15P21E102-99, so it is reported in the manifest and goes no further.
    """

    keywords: tuple[str, ...] = ()
    education: str | None = None
    employment_type: str | None = None
    salary: str | None = None
    headcount: str | None = None
    game_field: str | None = None
    # `수정` stamp. Kept separate from `posted_at`, which carries `등록`.
    updated_at: datetime | None = None


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


def detail_path(posting_id: str) -> str:
    """The posting detail page.

    `/Recruit/` is not in `robots.txt`. The disallowed listing path is
    `/List_GG/`, which this collector never requests — see the README.
    """

    return f"/Recruit/GI_Read/View?GI_No={posting_id}"


def parse_job_list(html: str, *, now: datetime) -> list[ListingRow]:
    """Extract every posting row from a 게임잡 listing page.

    `now` anchors the registration column, which the listing writes without a
    year and sometimes relative to the present ("3시간 전 등록").
    """

    root = parse_html(html)
    rows: list[ListingRow] = []
    seen: set[str] = set()

    for anchor in root.find_all("a"):
        href = (anchor.attrs.get("href") or "").strip()
        match = _POSTING_ID_RE.search(href)
        if not match:
            continue
        # Only the title link sits inside `div.tit`; the same posting is also
        # linked from banners and "최근 본 공고" blocks elsewhere on the page.
        container = _ancestor_with_class(anchor, "tit")
        if container is None:
            continue

        posting_id = match.group(1)
        if posting_id in seen:
            continue
        title = collapse(anchor.inner_text())
        if not title:
            continue

        row = _ancestor_tag(anchor, "tr")
        career_level, region = _info_fields(container)
        deadline_label, posted_on, _ = _date_cells(row, now=now)

        rows.append(
            ListingRow(
                source_posting_id=posting_id,
                # Rebuilt from the id rather than copied: the listing href is
                # the same shape, but rebuilding keeps one definition of the
                # detail path and drops any tracking parameters the site adds.
                detail_ref=detail_path(posting_id),
                title=title,
                company_name=_company_name(row) or None,
                career_level=career_level,
                region=region,
                raw_job_category=_listing_job_category(anchor),
                posted_on=posted_on,
                deadline_label=deadline_label,
            )
        )
        seen.add(posting_id)

    return rows


def listing_date_labels(html: str, *, now: datetime) -> list[str]:
    """Which date label each row used — `등록` or `수정`.

    Reported in the run manifest so a run states how many of its postings
    were dated by a modification date rather than a registration date.
    """

    root = parse_html(html)
    labels: list[str] = []
    for node in _all_with_class(root, "modifyDate"):
        parsed = parse_listing_posted_on(_text_of(node), now=now)
        if parsed is not None:
            labels.append(parsed[1])
    return labels


def _ancestor_with_class(node: HtmlNode, name: str) -> HtmlNode | None:
    current = node.parent
    while current is not None:
        if _has_class(current, name):
            return current
        current = current.parent
    return None


def _ancestor_tag(node: HtmlNode, tag: str) -> HtmlNode | None:
    current = node.parent
    while current is not None:
        if current.tag == tag:
            return current
        current = current.parent
    return None


def _company_name(row: HtmlNode | None) -> str:
    if row is None:
        return ""
    company = _first_with_class(row, "div", "company")
    return _text_of(company)


def _date_cells(
    row: HtmlNode | None,
    *,
    now: datetime,
) -> tuple[str | None, date | None, str | None]:
    """Read the deadline and registration cells.

    Returns `(deadline_label, posted_on, date_label)`. The two live in one
    `td` as `span.date` and `span.modifyDate`.
    """

    if row is None:
        return None, None, None
    deadline = _text_of(_first_with_class(row, "span", "date")) or None
    registered = _text_of(_first_with_class(row, "span", "modifyDate"))
    parsed = parse_listing_posted_on(registered, now=now)
    if parsed is None:
        return deadline, None, None
    return deadline, parsed[0], parsed[1]


def _info_fields(container: HtmlNode) -> tuple[str | None, str | None]:
    """Read 경력 and 지역 out of `p.info`.

    The block is a fixed run of spans — 경력, 학력, 지역, 게임분야, 고용형태 —
    but they are matched by wording rather than by index, so a site that drops
    the 학력 span does not shift every value silently. The region span is the
    one written as `시/도 > 구/군`, which is a stronger signal than position.
    """

    info = _first_with_class(container, "p", "info")
    if info is None:
        return None, None

    career: str | None = None
    region: str | None = None
    for span in info.find_all("span"):
        text = collapse(span.inner_text())
        if not text:
            continue
        if region is None and ">" in text:
            region = text
            continue
        if career is None and ("경력" in text or "신입" in text):
            career = text
    return career, region


def _listing_job_category(anchor: HtmlNode) -> str | None:
    """Read 모집분야 out of the title link's tracking call.

    The listing prints 경력·학력·지역·게임분야·고용형태 in `p.info` but not
    모집분야, and this call is the only place a row states it. Used to skip a
    detail fetch for an out-of-preset posting; the value stored on the record
    comes from the detail page. A miss returns None and the row is kept.
    """

    onclick = anchor.attrs.get("onclick") or ""
    match = _TRACKING_ARG_RE.search(onclick)
    if not match:
        return None
    value = html_module.unescape(match.group(1).replace("\\'", "'")).strip()
    if not value or value == "없음":
        return None
    return value


def parse_detail(html: str) -> GameJobDetail:
    """Extract the detail page's fields. The body needs a second request.

    `description_text` is always None here: the 담당업무 and 자격조건 text is
    inside iframes. The crawler fetches those and rebuilds the detail with
    `parse_body_fragment`. Returning an empty body rather than raising is what
    lets a restructured page become `body_status=PARSE_FAILED`.
    """

    root = parse_html(html)
    summary = _summary_fields(root)
    stamps = parse_detail_timestamps(_registration_text(root))

    return GameJobDetail(
        description_text=None,
        career_level=summary.get("career_level"),
        region=_detail_region(root),
        raw_job_category=summary.get("raw_job_category"),
        posted_at=stamps.get("등록"),
        deadline_label=summary.get("deadline_label"),
        section_names=_section_names(root),
        keywords=_split_tokens(summary.get("keywords")),
        education=summary.get("education"),
        employment_type=summary.get("employment_type"),
        salary=summary.get("salary"),
        headcount=summary.get("headcount"),
        game_field=summary.get("game_field"),
        updated_at=stamps.get("수정"),
    )


def _summary_fields(root: HtmlNode) -> dict[str, str]:
    """Read the `dt`/`dd` label rows.

    Only `dd` is read. Each row repeats its value inside a
    `div.tooltip-content`, so taking the whole `dl` text would store every
    value twice along with the tooltip's own button labels.
    """

    found: dict[str, str] = {}
    for definition in root.find_all("dl"):
        title = _first_with_class(definition, "dt", "recruit-data-title")
        if title is None:
            continue
        key = _SUMMARY_LABELS.get(collapse(title.inner_text()))
        if key is None or key in found:
            continue
        value = _text_of(_first_with_class(definition, "dd", "recruit-data-text"))
        if value:
            found[key] = value
    return found


def _registration_text(root: HtmlNode) -> str:
    """The `2026-07-03 17:07 등록` / `2026-09-08 14:02 수정` pair."""

    holder = _first_with_class(root, "div", "recruit-data-ddyytt")
    if holder is not None:
        return holder.inner_text()
    # The stamps are the only place the exact registration minute appears, so
    # a renamed wrapper falls back to scanning the labelled date paragraphs
    # rather than giving up and dating the posting by its listing row.
    return "\n".join(_text_of(node) for node in _all_with_class(root, "date"))


def _detail_region(root: HtmlNode) -> str | None:
    """근무지역, from the section of that name."""

    for title in _all_with_class(root, "job-sub-section__title"):
        if "근무지역" not in collapse(title.inner_text()):
            continue
        section = title.parent
        body = (
            _first_with_class(section, "div", "job-sub-section__body")
            if section is not None
            else None
        )
        text = collapse(body.inner_text()) if body is not None else ""
        if text:
            return text[:200]
    return None


def _section_names(root: HtmlNode) -> tuple[str, ...]:
    """Headings found in the posting, excluding the employer's own sections."""

    names: list[str] = []
    for title in _all_with_class(root, "job-sub-section__title"):
        text = collapse(title.inner_text())
        if not text or any(skip in text for skip in _NON_POSTING_SECTIONS):
            continue
        names.append(text)
    return tuple(dict.fromkeys(names))


def body_iframe_refs(html: str) -> tuple[tuple[str, str], ...]:
    """The `(section_name, src)` pairs holding the posting body.

    Read from the page rather than hardcoded, so a renamed endpoint yields no
    body — recorded as `PARSE_FAILED` — instead of a wrong one. Sections
    belonging to the employer rather than the posting are excluded here, so
    the crawler never spends a request on 기업정보.
    """

    root = parse_html(html)
    refs: list[tuple[str, str]] = []
    for section in _all_with_class(root, "job-sub-section"):
        title = _first_with_class(section, "div", "job-sub-section__title")
        name = collapse(title.inner_text()) if title is not None else ""
        if any(skip in name for skip in _NON_POSTING_SECTIONS):
            continue
        for frame in section.find_all("iframe"):
            src = (frame.attrs.get("src") or "").strip()
            if src:
                refs.append((name or frame.attrs.get("title", ""), src))
    # Same src under two headings would otherwise be fetched twice.
    return tuple({src: (name, src) for name, src in refs}.values())


def parse_body_fragment(html: str) -> tuple[str, tuple[str, ...]]:
    """Extract `(text, image_sources)` from one body iframe.

    The fragments are a full document each, carrying their own `<style>`
    block. `html_tree` drops `script`/`style`/`noscript`, so the CSS does not
    reach the text — which is the reason this uses the shared tree rather
    than a tag-stripping regex.
    """

    root = parse_html(html)
    body = root.find("body") or root
    return body.inner_text().strip(), _image_sources(body)


def _image_sources(body: HtmlNode) -> tuple[str, ...]:
    """Body images, skipping site chrome.

    Image-only postings are common on this site: the 담당업무 fragment is
    often a stack of uploaded artwork with no text at all.
    """

    sources: list[str] = []
    for image in body.find_all("img"):
        src = (image.attrs.get("src") or "").strip()
        if not src or any(marker in src for marker in _ASSET_HOST_MARKERS):
            continue
        sources.append(src)
    return tuple(dict.fromkeys(sources))


def _split_tokens(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    parts = [part.strip() for part in value.split(",")]
    return tuple(part for part in parts if part and part != "없음")
