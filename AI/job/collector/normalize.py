"""Site-agnostic mapping from parsed pages into `job-analysis-input/v1`.

S15P21E102-159 and S15P21E102-148 each wrote this mapping by hand and the two
copies had already drifted: Worknet's content-hash comment claimed
unit-separator delimiting that the code did not do, and technology extraction
existed only in the JobKorea package, so Worknet emitted an empty
`technology_mentions` tuple for every record. Both are fixed here once.

The rule this module exists to protect is the contract document §5: the
contract *does not* instruct the pipeline to perform unauthorized OCR or to
fabricate a missing body. So absence is mapped to a `body_status`, never
papered over — see `resolve_body_status`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo

from job.collector.interface import ListingRow, PostingDetail
from job.collector.technology import extract_technology_mentions
from job.contracts import (
    BodyStatus,
    JobPostingInput,
    PostingStatus,
    TechnologyMentionInput,
)

__all__ = [
    "OPEN_ENDED_DEADLINE_LABELS",
    "UNKNOWN_COMPANY_NAME",
    "content_hash_for",
    "dataset_snapshot_id_for",
    "normalize_posting",
    "pipeline_run_id_for",
    "posting_status_from_deadline",
    "resolve_body_status",
    "source_record_id_for",
]

# The contract requires a non-blank company_name, and public listings do carry
# rows with the employer withheld. A marker keeps the record instead of
# dropping a real posting over a field the analysis does not key on.
UNKNOWN_COMPANY_NAME = "(회사명 미표기)"

# Deadlines that never pass. Parsing these as dates would silently mark an
# open posting CLOSED.
OPEN_ENDED_DEADLINE_LABELS = (
    "채용시까지",
    "채용시",
    "상시채용",
    "수시채용",
    "상시모집",
)

# Field separator for the content hash. Without it "AB" + "C" and "A" + "BC"
# hash the same, so two different field splits of the same page would collide
# and one posting would be treated as a duplicate of the other.
_HASH_FIELD_SEPARATOR = "\x1f"
_SEOUL = ZoneInfo("Asia/Seoul")


def source_record_id_for(source_site: str, source_posting_id: str) -> str:
    """Namespace the site's own id so ids from two sites cannot collide."""

    return f"{source_site}:{source_posting_id}"


def pipeline_run_id_for(source_site: str, collected_at: datetime) -> str:
    """Identify one run. Stamped in UTC so runs sort across a DST boundary."""

    stamp = collected_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{source_site}-{stamp}"


def dataset_snapshot_id_for(
    source_site: str,
    start_date: date,
    end_date: date,
) -> str:
    """Identify what was asked for, so two runs of one range share an id."""

    return f"{source_site}-{start_date.isoformat()}-{end_date.isoformat()}"


def content_hash_for(
    *,
    source_site: str,
    source_posting_id: str,
    title: str,
    company_name: str,
    description_text: str | None,
) -> str:
    """Hash the fields that identify a posting's content, not its retrieval.

    `collected_at` and the run id are excluded on purpose: the same posting
    fetched twice must hash the same, or deduplication downstream cannot see
    that it is the same posting.
    """

    basis = _HASH_FIELD_SEPARATOR.join(
        (
            source_site,
            source_posting_id,
            title,
            company_name,
            description_text or "",
        )
    )
    return sha256(basis.encode("utf-8")).hexdigest()


def resolve_body_status(
    *,
    description_text: str | None,
    image_sources: tuple[str, ...],
    detail_fetched: bool,
    detail_error: str | None,
) -> BodyStatus:
    """Map what was actually retrieved onto the contract's five states.

    Order matters. Text wins because a page can carry both text and images.
    An image-only page stays IMAGE_ONLY — a caller may run OCR and append the
    result to the body, but it must not overwrite this status, since the
    contract does not license presenting OCR output as the source body.
    """

    if description_text and description_text.strip():
        return BodyStatus.TEXT_AVAILABLE
    if image_sources:
        return BodyStatus.IMAGE_ONLY
    if not detail_fetched:
        # A list-only run never asked for the body. Not an error.
        return BodyStatus.MISSING
    if detail_error:
        return BodyStatus.BLOCKED
    return BodyStatus.PARSE_FAILED


def posting_status_from_deadline(
    *,
    deadline_date: date | datetime | None,
    deadline_label: str | None,
    collected_at: datetime,
) -> PostingStatus:
    """Derive posting status from evidence only.

    Appearing in a live listing is evidence the posting is open, so a listed
    posting is ACTIVE unless its own deadline has already passed. Absence of a
    deadline is UNKNOWN, not ACTIVE: guessing would overstate what was seen.
    """

    if isinstance(deadline_date, datetime):
        if deadline_date.tzinfo is None or deadline_date.utcoffset() is None:
            raise ValueError("deadline timestamp must include a timezone")
        return (
            PostingStatus.CLOSED
            if deadline_date <= collected_at
            else PostingStatus.ACTIVE
        )
    if deadline_date is not None:
        return (
            PostingStatus.CLOSED
            if deadline_date < collected_at.astimezone(_SEOUL).date()
            else PostingStatus.ACTIVE
        )
    if deadline_label and any(
        label in deadline_label for label in OPEN_ENDED_DEADLINE_LABELS
    ):
        return PostingStatus.ACTIVE
    return PostingStatus.UNKNOWN


def normalize_posting(
    *,
    source_site: str,
    row: ListingRow,
    detail: PostingDetail | None,
    source_url: str,
    collected_at: datetime,
    detail_fetched: bool,
    deadline_date: date | datetime | None = None,
    detail_error: str | None = None,
    extract_technologies: bool = True,
) -> JobPostingInput:
    """Build one contract record. Raises `ValidationError` if it cannot.

    Callers keep their own invalid-record accounting, so a rejection is raised
    rather than swallowed — a record silently dropped here would leave a run
    reporting a count it did not collect.

    Detail values win over listing values field by field, because a detail
    page states them and a listing abbreviates them. Registration date is the
    exception the two collectors already learned: see `_posted_at_for`.
    """

    description_text = (detail.description_text or "").strip() if detail else ""
    image_sources = detail.image_sources if detail else ()

    body_status = resolve_body_status(
        description_text=description_text,
        image_sources=image_sources,
        detail_fetched=detail_fetched,
        detail_error=detail_error,
    )
    raw_artifact_uri = (
        image_sources[0] if body_status is BodyStatus.IMAGE_ONLY else None
    )

    deadline_label = (
        detail.deadline_label
        if detail and detail.deadline_label
        else row.deadline_label
    )
    company_name = (row.company_name or "").strip() or UNKNOWN_COMPANY_NAME
    title = row.title.strip()

    mentions: tuple[TechnologyMentionInput, ...] = ()
    if extract_technologies:
        mentions = extract_technology_mentions(title, description_text or None)

    payload: dict[str, Any] = {
        "source_record_id": source_record_id_for(source_site, row.source_posting_id),
        "source_site": source_site,
        "source_posting_id": row.source_posting_id,
        "source_url": source_url,
        "company_name": company_name,
        "title": title,
        "raw_job_category": _first(
            detail.raw_job_category if detail else None,
            row.raw_job_category,
        ),
        "career_level": _first(
            detail.career_level if detail else None,
            row.career_level,
        ),
        "region": _first(detail.region if detail else None, row.region),
        "description_text": description_text or None,
        "raw_artifact_uri": raw_artifact_uri,
        "body_status": body_status,
        "posting_status": posting_status_from_deadline(
            deadline_date=deadline_date,
            deadline_label=deadline_label,
            collected_at=collected_at,
        ),
        "posted_at": _posted_at_for(row, detail, collected_at),
        "deadline": _deadline_as_datetime(deadline_date),
        "collected_at": collected_at,
        "content_hash": content_hash_for(
            source_site=source_site,
            source_posting_id=row.source_posting_id,
            title=title,
            company_name=company_name,
            description_text=description_text or None,
        ),
        "technology_mentions": mentions,
    }
    return JobPostingInput.model_validate(payload)


def _first(*values: str | None) -> str | None:
    for value in values:
        if value is not None and value.strip():
            return value
    return None


def _posted_at_for(
    row: ListingRow,
    detail: PostingDetail | None,
    collected_at: datetime,
) -> datetime | None:
    """Prefer the detail timestamp, fall back to the listing's date column.

    S15P21E102-148 found what must never happen here: reaching into the body
    for "the first date that looks like one" stored deadlines as registration
    dates. When a detail page's label moves, the fallback is the listing
    column, which is labelled and therefore trustworthy — not the body.
    """

    if detail is not None and detail.posted_at is not None:
        return detail.posted_at
    return _as_datetime(row.posted_on, collected_at)


def _as_datetime(value: date | None, collected_at: datetime) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, datetime.min.time(), tzinfo=collected_at.tzinfo)


def _deadline_as_datetime(value: date | datetime | None) -> datetime | None:
    """Keep clock evidence; date-only values include their whole Seoul day."""

    if value is None or isinstance(value, datetime):
        return value
    return datetime.combine(value + timedelta(days=1), time.min, tzinfo=_SEOUL)
