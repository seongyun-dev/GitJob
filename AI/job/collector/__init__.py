"""Shared collector layer for job-posting sites (S15P21E102-99).

`job.contracts` fixes *what* crosses the A-to-C boundary. This package fixes
*how a site collector gets there*: the shapes a site parser produces, the
mapping into the contract, and the technology extraction every site shares.

A site package (`Worknet_Collector_V1`, `JobKorea_Collector_V1`, …) keeps only
what is genuinely site-specific — the HTTP client, the selectors, the date
formats — and implements `SiteCollector`.
"""

from job.collector.interface import ListingRow, PostingDetail, SiteCollector
from job.collector.normalize import (
    OPEN_ENDED_DEADLINE_LABELS,
    UNKNOWN_COMPANY_NAME,
    content_hash_for,
    dataset_snapshot_id_for,
    normalize_posting,
    pipeline_run_id_for,
    posting_status_from_deadline,
    resolve_body_status,
    source_record_id_for,
)
from job.collector.technology import (
    TECHNOLOGY_RULES,
    TechnologyRule,
    extract_technology_mentions,
)

__all__ = [
    "OPEN_ENDED_DEADLINE_LABELS",
    "TECHNOLOGY_RULES",
    "UNKNOWN_COMPANY_NAME",
    "ListingRow",
    "PostingDetail",
    "SiteCollector",
    "TechnologyRule",
    "content_hash_for",
    "dataset_snapshot_id_for",
    "extract_technology_mentions",
    "normalize_posting",
    "pipeline_run_id_for",
    "posting_status_from_deadline",
    "resolve_body_status",
    "source_record_id_for",
]
