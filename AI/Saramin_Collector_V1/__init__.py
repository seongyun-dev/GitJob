# ruff: noqa: N999

"""Saramin job-posting collector (S15P21E102-148)."""

from .categories import CATEGORY_PRESETS, resolve_category_preset
from .crawler import (
    COLLECTOR_VERSION,
    SOURCE_SITE,
    CrawlConfig,
    CrawlResult,
    Cursor,
    SaraminCrawler,
    write_outputs,
)

__all__ = [
    "CATEGORY_PRESETS",
    "COLLECTOR_VERSION",
    "SOURCE_SITE",
    "CrawlConfig",
    "CrawlResult",
    "Cursor",
    "SaraminCrawler",
    "resolve_category_preset",
    "write_outputs",
]
