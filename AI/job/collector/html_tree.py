"""Minimal HTML tree built on the standard library HTML parser.

The job sites collected here are server-rendered, so a small tree is enough.
Keeping it in the standard library avoids adding a scraping dependency to the
AI runtime image, which is why every collector shares this one rather than
pulling in a parser of its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

_IGNORED_TAGS = frozenset({"script", "style", "noscript", "template"})
_VOID_TAGS = frozenset(
    {
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
)
_BLOCK_TAGS = frozenset(
    {
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
)

_WHITESPACE_RE = re.compile(r"[ \t 　]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def clean_text(value: str | None) -> str:
    """Collapse inline whitespace while keeping block structure."""

    if not value:
        return ""
    # Blank lines are kept here on purpose: they mark block boundaries, and
    # the collapse below turns any run of them into a single paragraph break.
    lines = [_WHITESPACE_RE.sub(" ", line).strip() for line in value.splitlines()]
    return _BLANK_LINES_RE.sub("\n\n", "\n".join(lines)).strip()


def collapse(value: str | None) -> str:
    """Collapse all whitespace, including newlines, into single spaces."""

    if not value:
        return ""
    return _WHITESPACE_RE.sub(" ", value.replace("\n", " ")).strip()


@dataclass
class HtmlNode:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[HtmlNode] = field(default_factory=list)
    text: str = ""
    parent: HtmlNode | None = field(default=None, repr=False, compare=False)

    @property
    def classes(self) -> frozenset[str]:
        return frozenset(self.attrs.get("class", "").split())

    def iter_descendants(self) -> list[HtmlNode]:
        """Descendants in document order.

        Order matters: Worknet puts the company link before the posting link
        in the same row, and the listing itself is ordered by registration
        date, so a reversed walk would mislabel both.
        """

        found: list[HtmlNode] = []
        stack = list(reversed(self.children))
        while stack:
            node = stack.pop()
            found.append(node)
            stack.extend(reversed(node.children))
        return found

    def find_all(self, tag: str) -> list[HtmlNode]:
        return [node for node in self.iter_descendants() if node.tag == tag]

    def find(self, tag: str) -> HtmlNode | None:
        for node in self.iter_descendants():
            if node.tag == tag:
                return node
        return None

    def inner_text(self) -> str:
        """Text content with block-level tags rendered as line breaks."""

        parts: list[str] = []
        self._collect_text(parts)
        return clean_text("".join(parts))

    def _collect_text(self, parts: list[str]) -> None:
        if self.tag in _IGNORED_TAGS:
            return
        if self.tag == "#text":
            parts.append(self.text)
            return
        block = self.tag in _BLOCK_TAGS
        if block:
            parts.append("\n")
        for child in self.children:
            child._collect_text(parts)
        if block:
            parts.append("\n")


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode(tag="#root")
        self._stack: list[HtmlNode] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = HtmlNode(
            tag=tag,
            attrs={key: (value or "") for key, value in attrs},
            parent=self._stack[-1],
        )
        self._stack[-1].children.append(node)
        if tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        node = HtmlNode(
            tag=tag,
            attrs={key: (value or "") for key, value in attrs},
            parent=self._stack[-1],
        )
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if not data:
            return
        parent = self._stack[-1]
        parent.children.append(HtmlNode(tag="#text", text=data, parent=parent))


def parse_html(html: str) -> HtmlNode:
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


def ancestor_row(node: HtmlNode) -> HtmlNode | None:
    """Nearest enclosing table row, if any."""

    current = node.parent
    while current is not None:
        if current.tag == "tr":
            return current
        current = current.parent
    return None
