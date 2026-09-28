"""Small, dependency-free parsers for JobKorea's classic list and detail HTML."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from html.parser import HTMLParser

_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "ul",
}
_IGNORED_TAGS = {"script", "style", "noscript", "template"}
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


def clean_text(value: str | None) -> str:
    """Collapse HTML whitespace while retaining Korean punctuation and symbols."""

    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


@dataclass
class HtmlNode:
    """Minimal HTML tree node used instead of a third-party HTML dependency."""

    tag: str
    attrs: dict[str, str]
    children: list[HtmlNode | str]
    parent: HtmlNode | None = None

    def iter_nodes(self) -> Iterable[HtmlNode]:
        yield self
        for child in self.children:
            if isinstance(child, HtmlNode):
                yield from child.iter_nodes()

    def find_all(
        self,
        tag: str | None = None,
        *,
        id_value: str | None = None,
        class_contains: str | None = None,
        predicate: Callable[[HtmlNode], bool] | None = None,
    ) -> list[HtmlNode]:
        result: list[HtmlNode] = []
        for node in self.iter_nodes():
            if tag is not None and node.tag != tag:
                continue
            if id_value is not None and node.attrs.get("id") != id_value:
                continue
            if class_contains is not None and not node.has_class(class_contains):
                continue
            if predicate is not None and not predicate(node):
                continue
            result.append(node)
        return result

    def find_first(
        self,
        tag: str | None = None,
        *,
        id_value: str | None = None,
        class_contains: str | None = None,
        predicate: Callable[[HtmlNode], bool] | None = None,
    ) -> HtmlNode | None:
        matches = self.find_all(
            tag,
            id_value=id_value,
            class_contains=class_contains,
            predicate=predicate,
        )
        return matches[0] if matches else None

    def has_class(self, class_name: str) -> bool:
        return class_name in self.attrs.get("class", "").split()

    def text_lines(self) -> list[str]:
        raw = self._raw_text()
        return [clean_text(line) for line in raw.splitlines() if clean_text(line)]

    def text_content(self) -> str:
        return clean_text(self._raw_text().replace("\n", " "))

    def _raw_text(self) -> str:
        if self.tag in _IGNORED_TAGS:
            return ""

        parts: list[str] = []
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
                continue
            if child.tag in _IGNORED_TAGS:
                continue
            if child.tag == "br":
                parts.append("\n")
                continue
            if child.tag in _BLOCK_TAGS:
                parts.append("\n")
            parts.append(child._raw_text())
            if child.tag in _BLOCK_TAGS:
                parts.append("\n")
        return "".join(parts)


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("#document", {}, [])
        self._stack: list[HtmlNode] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = HtmlNode(
            tag.lower(),
            {key.lower(): value or "" for key, value in attrs},
            [],
            self._stack[-1],
        )
        self._stack[-1].children.append(node)
        if node.tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)
        if self._stack[-1].tag == tag.lower():
            self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].children.append(data)


def parse_html(html: str) -> HtmlNode:
    parser = _TreeBuilder()
    parser.feed(html)
    parser.close()
    return parser.root


_POSTING_ID_RE = re.compile(r"/Recruit/GI_Read/(\d+)", re.IGNORECASE)
_CAREER_RE = re.compile(
    r"^(?:신입(?:[·/]경력)?|경력무관|경력\s*\d+년(?:\s*이상|↑|\+)?|경력)$"
)
_EDUCATION_RE = re.compile(
    r"^(?:학력무관|고졸이상|고졸↑|초대졸↑|대졸↑|대학원졸업|대학교졸업|\S+졸업)$"
)
_EMPLOYMENT_RE = re.compile(
    r"(?:정규직|계약직|인턴|파견직|프리랜서|아르바이트|위촉직|교육생|연수생|기간제|무기계약직)"
)
_REGION_RE = re.compile(
    r"^(?:서울|경기|인천|부산|대구|대전|광주|울산|세종|강원|충북|충남|전북|전남|경북|경남|제주|전국|해외)\b"
)
_DATE_RE = re.compile(r"(?:(?:20\d{2})[./-])?\d{1,2}[./-]\d{1,2}(?:\s*\([^)]*\))?")
_CSS_URL_RE = re.compile(r"url\(\s*['\"]?([^'\")]+)", re.IGNORECASE)


@dataclass(frozen=True)
class JobListItem:
    posting_id: str
    source_url: str
    company_name: str
    title: str
    raw_job_category: str | None
    career_level: str | None
    region: str | None
    posted_label: str | None
    deadline_label: str | None


@dataclass(frozen=True)
class DetailContent:
    description_text: str | None
    body_status: str
    has_images: bool
    deadline_label: str | None
    image_sources: tuple[str, ...] = ()


def _find_list_scope(root: HtmlNode) -> HtmlNode:
    scoped = root.find_first(id_value="dev-gi-list")
    if scoped is not None:
        return scoped

    containers = root.find_all(
        predicate=lambda node: (
            node.tag in {"div", "table"} and node.has_class("tplJobList")
        )
    )
    return containers[0] if containers else root


def _posting_id_from_row(row: HtmlNode, href: str) -> str | None:
    data_gno = row.attrs.get("data-gno", "").strip()
    if data_gno.isdigit():
        return data_gno
    data_info = row.attrs.get("data-info", "").strip()
    if data_info:
        first = data_info.split("|", 1)[0].strip()
        if first.isdigit():
            return first
    match = _POSTING_ID_RE.search(href)
    return match.group(1) if match else None


def _title_link(row: HtmlNode) -> HtmlNode | None:
    links = row.find_all(
        "a",
        predicate=lambda node: bool(_POSTING_ID_RE.search(node.attrs.get("href", ""))),
    )
    if not links:
        return None
    return next(
        (link for link in links if link.attrs.get("title", "").strip()),
        links[0],
    )


def _company_name(row: HtmlNode) -> str:
    company_cell = row.find_first("td", class_contains="tplCo")
    if company_cell is not None:
        company_links = company_cell.find_all(
            "a",
            predicate=lambda node: "/Recruit/Co_Read/" in node.attrs.get("href", ""),
        )
        if company_links:
            return company_links[0].text_content()

    lines = row.text_lines()
    return lines[0] if lines else ""


def _metadata_cells(row: HtmlNode) -> list[str]:
    details = row.find_first("p", class_contains="etc")
    if details is None:
        return []
    cells = details.find_all("span", class_contains="cell")
    return [cell.text_content() for cell in cells if cell.text_content()]


def _career_and_region(cells: list[str]) -> tuple[str | None, str | None]:
    career = next((value for value in cells if _CAREER_RE.fullmatch(value)), None)
    education_index = next(
        (index for index, value in enumerate(cells) if _EDUCATION_RE.fullmatch(value)),
        -1,
    )

    region: str | None = None
    for value in cells[education_index + 1 :]:
        if _REGION_RE.match(value):
            region = value
            break
    if region is None and education_index >= 0:
        for value in cells[education_index + 1 :]:
            if not _EMPLOYMENT_RE.search(value):
                region = value
                break
    return career, region


def _row_deadline(row: HtmlNode) -> str | None:
    date_node = row.find_first("span", class_contains="date")
    if date_node is not None:
        value = date_node.text_content()
        if value:
            return value
    for line in row.text_lines():
        if (
            "상시채용" in line
            or "마감" in line
            or re.search(r"~\s*\d{1,2}[./-]\d{1,2}", line)
        ):
            return line
    return None


def parse_job_list(
    html: str,
    base_url: str = "https://www.jobkorea.co.kr",
) -> list[JobListItem]:
    """Extract ordinary category-list rows from a JobKorea response."""

    root = parse_html(html)
    scope = _find_list_scope(root)
    result: list[JobListItem] = []
    seen_ids: set[str] = set()
    for row in scope.find_all("tr"):
        if not row.attrs.get("data-gno") and not row.attrs.get("data-info"):
            continue
        link = _title_link(row)
        if link is None:
            continue
        href = link.attrs.get("href", "")
        posting_id = _posting_id_from_row(row, href)
        if posting_id is None or posting_id in seen_ids:
            continue
        seen_ids.add(posting_id)

        title = clean_text(link.attrs.get("title") or link.text_content())
        if not title:
            continue
        title_cell = row.find_first("td", class_contains="tplTit")
        category_node = (
            title_cell.find_first("p", class_contains="dsc")
            if title_cell is not None
            else None
        )
        raw_category = category_node.text_content() if category_node is not None else ""
        cells = _metadata_cells(row)
        career, region = _career_and_region(cells)
        time_node = row.find_first("span", class_contains="time")
        posted_label = time_node.text_content() if time_node is not None else None

        canonical_url = f"{base_url.rstrip('/')}/Recruit/GI_Read/{posting_id}"
        result.append(
            JobListItem(
                posting_id=posting_id,
                source_url=canonical_url,
                company_name=_company_name(row),
                title=title,
                raw_job_category=raw_category or None,
                career_level=career,
                region=region,
                posted_label=posted_label or None,
                deadline_label=_row_deadline(row),
            )
        )
    return result


def extract_deadline_label(text: str) -> str | None:
    """Find a closing date near application/marquee wording in detail text."""

    lines = [line for line in text.splitlines() if clean_text(line)]
    context_terms = ("접수", "마감", "채용시")
    for index, line in enumerate(lines):
        if not any(term in line for term in context_terms):
            continue
        segment = " ".join(lines[index : index + 4])
        if "상시채용" in segment or "채용시마감" in segment:
            match = _DATE_RE.search(segment)
            return match.group(0) if match else "상시채용"
        match = _DATE_RE.search(segment)
        if match:
            return match.group(0)

    if "상시채용" in text or "채용시마감" in text:
        return "상시채용"
    return None


def _image_sources(body: HtmlNode) -> tuple[str, ...]:
    sources: list[str] = []
    seen: set[str] = set()
    for image in body.find_all("img"):
        for attribute in (
            "src",
            "srcset",
            "data-src",
            "data-original",
            "data-lazy-src",
        ):
            raw_value = image.attrs.get(attribute, "").strip()
            raw_sources = raw_value.split(",") if attribute == "srcset" else [raw_value]
            for raw_source in raw_sources:
                source_parts = raw_source.strip().split(maxsplit=1)
                if not source_parts:
                    continue
                source = source_parts[0]
                if source and not source.startswith("data:") and source not in seen:
                    seen.add(source)
                    sources.append(source)
    for node in body.iter_nodes():
        style = node.attrs.get("style", "")
        for match in _CSS_URL_RE.finditer(style):
            source = match.group(1).strip()
            if source and not source.startswith("data:") and source not in seen:
                seen.add(source)
                sources.append(source)
    return tuple(sources)


def parse_detail(html: str) -> DetailContent:
    """Parse the body iframe returned by ``GI_Read_Comt_Ifrm``."""

    root = parse_html(html)
    body = root.find_first("body") or root
    lines = body.text_lines()
    description = "\n".join(lines) or None
    image_sources = _image_sources(body)
    has_images = bool(body.find_all("img")) or bool(image_sources)
    if description:
        body_status = "TEXT_AVAILABLE"
    elif has_images:
        body_status = "IMAGE_ONLY"
    else:
        body_status = "MISSING"
    return DetailContent(
        description_text=description,
        body_status=body_status,
        has_images=has_images,
        deadline_label=extract_deadline_label(description or ""),
        image_sources=image_sources,
    )
