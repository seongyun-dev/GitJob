
"""Backwards-compatible re-export of the shared minimal HTML tree.

Moved to `job.collector.html_tree` when the Saramin collector was added: it
would have been a third copy of the same standard-library tree, and nothing in
it was ever Worknet-specific. This module keeps the old import path working.
"""

from job.collector.html_tree import (
    HtmlNode,
    ancestor_row,
    clean_text,
    collapse,
    parse_html,
)

__all__ = [
    "HtmlNode",
    "ancestor_row",
    "clean_text",
    "collapse",
    "parse_html",
]
