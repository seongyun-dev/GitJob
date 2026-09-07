"""Backwards-compatible re-export of the shared technology extractor.

The extractor moved to `job.collector.technology` in S15P21E102-99 because it
never depended on JobKorea: it matches rules against title and body text that
any site produces. Worknet was emitting an empty `technology_mentions` tuple
only because the code lived here. This module keeps the old import path
working so S15P21E102-159 callers do not have to change.
"""

from job.collector.technology import (
    TECHNOLOGY_RULES,
    TechnologyRule,
    extract_technology_mentions,
)

__all__ = [
    "TECHNOLOGY_RULES",
    "TechnologyRule",
    "extract_technology_mentions",
]
