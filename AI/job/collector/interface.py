"""The interface a site collector implements (S15P21E102-99).

The `job-analysis-input/v1` contract in `job.contracts` is fixed by
S15P21E102-90 and is not redefined here. What was still missing is the layer
below it: every site parser was inventing its own row and detail shapes, so the
mapping into the contract was rewritten per site. S15P21E102-159 (JobKorea) and
S15P21E102-148 (Worknet) ended up with two `JobListItem` dataclasses whose
fields differed in name and type, two block-detecting HTTP clients, and two
copies of the body-status decision.

This module fixes the shapes. A site collector parses HTML into `ListingRow`
and `PostingDetail`; `job.collector.normalize` turns those into a contract
record. Nothing about a specific site belongs here.

### What the interface deliberately does not carry

- **Education and graduation status.** S15P21E102-99 puts them outside the
  storage scope, so there is no field to put them in. A site parser may read
  them for its own filtering, but they stop at the parser.
- **Language ability.** The ticket keeps it "parsed but not validated", which
  means it stays in `description_text` as written. Promoting it to a typed
  field would imply a validation this pipeline does not perform.
- **Registry technology ids.** The A-to-C boundary carries raw mentions only
  (`job.contracts` §TechnologyMentionInput). Matching happens downstream.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol, runtime_checkable

__all__ = [
    "ListingRow",
    "PostingDetail",
    "SiteCollector",
]


@dataclass(frozen=True)
class ListingRow:
    """One row of a site's search listing.

    A listing row is evidence that the posting is live, and on most sites it
    carries fields the detail page omits or formats worse. It is kept as a
    distinct input rather than merged into the detail so the normalizer can
    fall back to it field by field.
    """

    source_posting_id: str
    # Href or path as it appears in the listing. The collector resolves it to
    # an absolute URL via `absolute_url`; the normalizer never guesses a host.
    detail_ref: str
    title: str
    company_name: str | None = None
    career_level: str | None = None
    region: str | None = None
    raw_job_category: str | None = None
    # Registration date as shown in the listing. Sites label this column, so
    # it is the trustworthy source when a detail page's label moves.
    posted_on: date | None = None
    # Kept as the site's own text, not a date: "채용시까지" is a deadline the
    # contract represents through `posting_status`, not through `deadline`.
    deadline_label: str | None = None


@dataclass(frozen=True)
class PostingDetail:
    """Readable content pulled from one detail page.

    Every field is optional because a detail page may be blocked, image-only,
    or restructured. Absence must stay representable — the normalizer maps it
    to a `body_status`, and inventing a value here would defeat that.
    """

    description_text: str | None = None
    career_level: str | None = None
    region: str | None = None
    raw_job_category: str | None = None
    posted_at: datetime | None = None
    deadline_label: str | None = None
    # **Absolute** URIs. The collector resolves them before returning, so the
    # normalizer can put one straight into `raw_artifact_uri` for an
    # IMAGE_ONLY record without knowing the site's host.
    image_sources: tuple[str, ...] = ()
    # Section headings found in the body. Diagnostic only: a sudden drop is
    # how a layout change shows up in a manifest.
    section_names: tuple[str, ...] = field(default=())


@runtime_checkable
class SiteCollector(Protocol):
    """What a site must provide to be collected into the common contract.

    Parsing is separated from fetching on purpose: both methods take HTML and
    return data, so a site's extraction is testable against a saved page with
    no network and no client.
    """

    @property
    def source_site(self) -> str:
        """Uppercase site key, e.g. `WORKNET`.

        The S15P21E102-90 fixtures use uppercase, and aggregation splits
        denominators by this value (S15P21E102-94 §3.5), so it must be stable
        across runs — never a display name.
        """

    @property
    def collector_version(self) -> str:
        """Version written into the batch, e.g. `worknet-collector/v1`."""

    def parse_list(self, html: str) -> Sequence[ListingRow]:
        """Extract listing rows. Returns empty for a page with no results."""

    def parse_detail(self, html: str) -> PostingDetail:
        """Extract one detail page. Must not raise on unexpected markup.

        A parser that cannot find the body returns a `PostingDetail` with
        `description_text=None` and lets the normalizer record
        `body_status=PARSE_FAILED`. Raising would lose the row entirely.
        """

    def absolute_url(self, ref: str) -> str:
        """Resolve a listing `detail_ref` to the absolute `source_url`."""
