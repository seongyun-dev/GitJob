# ruff: noqa: N999

"""커리어(career.co.kr) job-posting collector.

기준 A 미통과 상태에서 소유자 결정으로 만들어진 수집기입니다. 근거는
`crawler.py` 모듈 docstring 과 각 회차 manifest 의 `source_admission` 에
기록돼 있습니다.
"""

from .crawler import (
    CATEGORY_PRESETS,
    COLLECTOR_VERSION,
    JOB_CATEGORIES,
    SOURCE_SITE,
    CareerCrawler,
    CrawlConfig,
    CrawlResult,
    Cursor,
    write_outputs,
)

__all__ = [
    "CATEGORY_PRESETS",
    "COLLECTOR_VERSION",
    "JOB_CATEGORIES",
    "SOURCE_SITE",
    "CareerCrawler",
    "CrawlConfig",
    "CrawlResult",
    "Cursor",
    "write_outputs",
]
