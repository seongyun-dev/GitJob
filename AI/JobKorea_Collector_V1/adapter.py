"""Adapter from JobKorea parser results to the shared collector contract."""

from __future__ import annotations

from datetime import datetime

from job.collector import ListingRow, PostingDetail, normalize_posting
from job.contracts import BodyStatus, JobPostingInput

from .parser import DetailContent, JobListItem

SOURCE_SITE = "JOBKOREA"


def listing_row_from_jobkorea(
    item: JobListItem,
    *,
    posted_at: datetime | None,
) -> ListingRow:
    """Keep listing evidence while adopting the shared field names.

    ``posted_at`` is optional because the v3 active-scope mode selects a
    listing on the strength of it being listed, not on its registration date.
    A label the parser could not read therefore reaches here as ``None``, and
    `ListingRow.posted_on` is ``date | None`` for exactly that case -- the
    shared normalizer maps the absence through to ``posted_at=None``. Guessing
    a date here would be indistinguishable from a real one downstream.
    """

    return ListingRow(
        source_posting_id=item.posting_id,
        detail_ref=item.source_url,
        title=item.title,
        company_name=item.company_name or None,
        career_level=item.career_level,
        region=item.region,
        raw_job_category=item.raw_job_category,
        posted_on=posted_at.date() if posted_at is not None else None,
        deadline_label=item.deadline_label,
    )


def posting_detail_from_jobkorea(
    detail: DetailContent | None,
    *,
    description_text: str | None,
    image_sources: tuple[str, ...],
    posted_at: datetime | None,
) -> PostingDetail | None:
    """Move the source body plus optional OCR text into the common detail."""

    if detail is None:
        return None
    return PostingDetail(
        description_text=description_text,
        posted_at=posted_at,
        deadline_label=detail.deadline_label,
        image_sources=image_sources,
    )


def normalize_jobkorea_posting(
    *,
    item: JobListItem,
    detail: DetailContent | None,
    description_text: str | None,
    image_sources: tuple[str, ...],
    posted_at: datetime | None,
    deadline: datetime | None,
    collected_at: datetime,
    detail_fetched: bool,
    detail_error: str | None,
) -> JobPostingInput:
    """Normalize one JobKorea posting without duplicating contract logic.

    OCR text is analysis text, not evidence that the source had an HTML text
    body. For an image-only posting we therefore restore ``IMAGE_ONLY`` after
    the shared normalizer has extracted technologies from the OCR-appended
    description.
    """

    row = listing_row_from_jobkorea(item, posted_at=posted_at)
    common_detail = posting_detail_from_jobkorea(
        detail,
        description_text=description_text,
        image_sources=image_sources,
        posted_at=posted_at,
    )
    record = normalize_posting(
        source_site=SOURCE_SITE,
        row=row,
        detail=common_detail,
        source_url=item.source_url,
        collected_at=collected_at,
        detail_fetched=detail_fetched,
        deadline_date=deadline,
        detail_error=detail_error,
    )

    source_was_image_only = (
        detail is not None and detail.body_status == BodyStatus.IMAGE_ONLY.value
    )
    if not source_was_image_only:
        return record

    payload = record.model_dump(mode="python", by_alias=True)
    payload["body_status"] = BodyStatus.IMAGE_ONLY
    payload["raw_artifact_uri"] = image_sources[0] if image_sources else item.source_url
    return JobPostingInput.model_validate(payload)


__all__ = [
    "SOURCE_SITE",
    "listing_row_from_jobkorea",
    "normalize_jobkorea_posting",
    "posting_detail_from_jobkorea",
]
