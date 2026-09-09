# ruff: noqa: N999

"""게임잡 job-posting collector."""

from .crawler import (
    COLLECTOR_VERSION,
    SOURCE_SITE,
    CrawlConfig,
    CrawlResult,
    Cursor,
    GameJobCrawler,
    write_outputs,
)
from .duties import DUTY_CODES, DUTY_PRESETS, resolve_duty_preset

__all__ = [
    "COLLECTOR_VERSION",
    "DUTY_CODES",
    "DUTY_PRESETS",
    "SOURCE_SITE",
    "CrawlConfig",
    "CrawlResult",
    "Cursor",
    "GameJobCrawler",
    "resolve_duty_preset",
    "write_outputs",
]
