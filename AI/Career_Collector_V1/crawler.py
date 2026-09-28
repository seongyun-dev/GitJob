"""커리어(career.co.kr) 채용공고 수집기.

Writes a `job-analysis-input/v1` batch (S15P21E102-90) through the shared
collector layer (S15P21E102-99), the same as 워크넷·사람인·게임잡.

### Source admission — read this before enabling a scheduled run

커리어 **does not pass 기준 A** as written in
`docs/data/2026-08-31-jobkorea-retention-decision.md` §4. The measurement,
2026-09-09:

- Operator is (주)커리어넷, 사업자등록번호 220-86-73547 — a **different legal
  entity** from 웍스피어/잡코리아 (110-81-34859), so the case law that
  disqualified 게임잡 does not reach here.
- `job.career.co.kr/robots.txt` **allows** the posting paths. Only `/admin`,
  `/app`, `/base`, `/biz`, `/user` and `/signup` are disallowed, and a
  `sitemap.xml` is published. None of the paths this collector requests are
  disallowed.
- 이용약관 **제14조 5항**: "이용자는 커리어서비스 이용을 통해 획득한 정보 및
  게시물을 커리어넷의 **동의없이 복제, 배포할 수 없으며** 상업적, 영리목적으로
  이용할 수 없습니다." 제20조 6·7항 repeat it.

기준 A is an OR condition, so robots.txt allowing is not sufficient. Storing
postings in HDFS is 복제. There is no clause naming 크롤링 or 스크래핑 — this
is weaker than 링커리어, whose 제20조 prohibits scraping outright — but it is
a prohibition all the same.

**This collector exists because the project owner decided to proceed after
being shown 제14조 5항.** That is recorded here rather than in a commit
message so nobody re-derives the admission from the code's existence. The
scheduled runs ship `enabled = false` for the same reason 게임잡's do: turning
them on has to be a deliberate act, not an inherited default.

### What the site is

Two 직종 대분류 hold the developer postings, and `i_jc1` filters them
server-side:

    H0  IT.인터넷              227 postings, listing ends at page 8
    N0  연구개발.엔지니어      still serving rows at page 12

Measured 2026-09-09 with `i_pagesize=30`. Unlike 게임잡, `page` genuinely
advances: pages 2 and 3 shared no posting ids at all.

### Two things that would silently break a run

**The listing is not ordered by registration date.** Page 2 of H0 carried
postings registered 2026-06-15 through 2026-07-02 while page 1 carried newer
ones. So there is no early stop on an out-of-range page — the whole listing is
read and the date filter runs per row. This is also why the site is worth
collecting: 상시채용 postings stay listed for months, where 워크넷 drops
closed postings and leaves only ~2 months of history.

**Ad slots are not rows.** A page carries far more `/recruit/view/` links than
postings and the extras rotate, so counting links would never see the end.
`parser._listing_rows` takes only real table rows; page 9 of H0 then parses as
zero rows and the run stops. See the parser's docstring.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from job.collector import (
    ListingRow,
    dataset_snapshot_id_for,
    normalize_posting,
    pipeline_run_id_for,
)
from job.collector.analysis_input import publish_from_env
from job.collector.outcome import collector_exit_code
from job.collector.http import BlockedError, HttpError, PoliteHttpClient
from job.collector.identity import (
    Decision,
    PostingIdentityStore,
    identity_path_for,
)
from job.collector.raw_sink import sink_from_env, write_upload_record
from job.contracts import (
    JOB_ANALYSIS_INPUT_SCHEMA_VERSION,
    JobAnalysisInputBatch,
    JobPostingInput,
)

from .dates import as_seoul, parse_deadline
from .parser import listing_date_labels, parse_detail, parse_job_list

COLLECTOR_VERSION = "career-collector/v1"
# Uppercase to match the source_site convention in the S15P21E102-90 fixture.
SOURCE_SITE = "CAREER"
# Postings live on the `job.` host, not `www.`. The two have separate
# robots.txt files and only this one's was measured for the posting paths.
DEFAULT_BASE_URL = "https://job.career.co.kr"
LIST_PATH = "/jobs/jobpart"

# The listing's own selector offers 5/10/15/20/25/30 and the form defaults to
# 30. Requesting the maximum keeps the request count per posting down.
LISTING_PAGE_SIZE = 30
# H0 ended at page 8 and N0 was still going at 12. 40 leaves room for the
# listing to grow without a run walking forever; the real stop is an empty
# page.
DEFAULT_MAX_PAGES = 40
# A commercial site with no API grant and no data-provision agreement, so the
# interval matches 사람인·게임잡 rather than 워크넷's 1.0s.
DEFAULT_REQUEST_DELAY = 2.0
# `i_so=3` is what the site's own form submits. Kept as the site's default
# rather than reordering a listing we do not control.
LISTING_SORT = "3"

# 직종 대분류 codes, with the site's names for the manifest.
JOB_CATEGORIES: dict[str, str] = {
    "A0": "경영.기획",
    "B0": "마케팅.광고",
    "C0": "전문직",
    "E0": "영업.고객상담.판매",
    "F0": "생산.제조",
    "H0": "IT.인터넷",
    "I0": "디자인",
    "N0": "연구개발.엔지니어",
}

# Named sets so a scheduled run declares intent instead of a bare code.
CATEGORY_PRESETS: dict[str, tuple[str, ...]] = {
    # The two 대분류 that hold developer postings. Both are needed: embedded
    # and R&D roles sit under 연구개발.엔지니어, not IT.인터넷.
    "dev": ("H0", "N0"),
    # IT.인터넷 only, for a shorter run.
    "it": ("H0",),
}


@dataclass(frozen=True)
class CrawlConfig:
    start_date: date
    end_date: date
    categories: tuple[str, ...] = CATEGORY_PRESETS["dev"]
    category_preset: str | None = None
    max_pages: int = DEFAULT_MAX_PAGES
    request_delay: float = DEFAULT_REQUEST_DELAY
    fetch_detail: bool = True
    base_url: str = DEFAULT_BASE_URL
    cursor_path: Path | None = None
    page_size: int = LISTING_PAGE_SIZE
    # Fixed clock. A recently posted row dates itself relative to the present
    # ("13시간 전 등록"), so a test with fixture markup needs to pin "now" to
    # stay deterministic. Same override 게임잡 and JobKorea carry.
    now: datetime | None = None

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        if self.max_pages < 1:
            raise ValueError("max_pages must be positive")
        if self.request_delay < 0:
            raise ValueError("request_delay must not be negative")
        if not self.categories:
            raise ValueError("at least one 직종 대분류 is required")
        unknown = [code for code in self.categories if code not in JOB_CATEGORIES]
        if unknown:
            raise ValueError(f"unknown 직종 대분류: {', '.join(unknown)}")
        if self.page_size < 1:
            raise ValueError("page_size must be positive")


@dataclass
class Cursor:
    """Resume state for this site.

    The listing is not ordered by registration date and offers no stable
    offset, so the cursor stores the posting ids already validated in this
    date range and a re-run skips them. Same shape as 사람인·게임잡 for the
    same reason.
    """

    start_date: str
    end_date: str
    collected_ids: list[str] = field(default_factory=list)
    last_page: int = 0
    updated_at: str | None = None

    @classmethod
    def load(cls, path: Path | None, config: CrawlConfig) -> Cursor:
        fresh = cls(
            start_date=config.start_date.isoformat(),
            end_date=config.end_date.isoformat(),
        )
        if path is None or not path.exists():
            return fresh
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return fresh
        if (
            raw.get("start_date") != fresh.start_date
            or raw.get("end_date") != fresh.end_date
        ):
            return fresh
        ids = raw.get("collected_ids")
        return cls(
            start_date=fresh.start_date,
            end_date=fresh.end_date,
            collected_ids=[str(item) for item in ids] if isinstance(ids, list) else [],
            last_page=int(raw.get("last_page") or 0),
            updated_at=raw.get("updated_at"),
        )

    def save(self, path: Path | None) -> None:
        if path is None:
            return
        self.updated_at = datetime.now(UTC).isoformat()
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(
            path,
            json.dumps(
                {
                    "start_date": self.start_date,
                    "end_date": self.end_date,
                    "collected_ids": self.collected_ids,
                    "last_page": self.last_page,
                    "updated_at": self.updated_at,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )


@dataclass(frozen=True)
class CrawlResult:
    batch: JobAnalysisInputBatch
    manifest: dict[str, Any]
    # Resume state and where it belongs. `write_outputs` writes it last, so
    # the cursor cannot claim postings whose batch was never stored — the
    # failure that cost 사람인 3,072 postings across 2026-09-08 and -09
    # (S15P21E102-174). Defaulted so a caller building a result by hand
    # simply gets no resume state.
    cursor: Cursor | None = None
    cursor_path: Path | None = None
    # Cross-run identity, persisted next to the cursor and for the same reason:
    # only once the batch is on disk. The cursor forgets its ids the moment the
    # run's date range moves; this store carries no range and does not.
    identity: PostingIdentityStore | None = None
    identity_path: Path | None = None


ProgressCallback = Callable[[str], None]


class CareerCrawler:
    def __init__(
        self,
        config: CrawlConfig,
        client: PoliteHttpClient | None = None,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self.config = config
        self.client = client or PoliteHttpClient(base_url=config.base_url)
        self._on_progress = on_progress

    def _progress(self, message: str) -> None:
        if self._on_progress is not None:
            self._on_progress(message)

    def _list_params(self, category: str, page: int) -> list[tuple[str, str]]:
        return [
            ("i_jc1", category),
            ("page", str(page)),
            ("i_pagesize", str(self.config.page_size)),
            ("i_so", LISTING_SORT),
        ]

    def _fetch_list_page(
        self,
        category: str,
        page: int,
        *,
        now: datetime,
    ) -> tuple[list[ListingRow], list[str]]:
        html = self.client.get(
            LIST_PATH,
            self._list_params(category, page),
            delay_seconds=self.config.request_delay if page > 1 else 0.0,
        )
        return (
            list(parse_job_list(html, now=now)),
            listing_date_labels(html, now=now),
        )

    def _fetch_detail(self, item: ListingRow):
        """Fetch and parse one detail page. The body is inline — no iframes."""

        if not self.config.fetch_detail:
            # A deliberate list-only run, mapped to body_status=MISSING by the
            # shared normalizer. Not an error.
            return None, None
        try:
            html = self.client.get(
                item.detail_ref,
                referer=self.client.absolute(LIST_PATH),
                delay_seconds=self.config.request_delay,
            )
        except BlockedError:
            raise
        except HttpError as error:
            return None, str(error)

        try:
            detail = parse_detail(html)
        except Exception as error:  # noqa: BLE001 - parser must not abort a run
            return None, f"detail parse failed: {error}"

        # The interface requires absolute image URIs so the normalizer can put
        # one straight into `raw_artifact_uri` without knowing the host.
        return (
            replace(
                detail,
                image_sources=tuple(
                    dict.fromkeys(
                        self.client.absolute(src) for src in detail.image_sources
                    )
                ),
            ),
            None,
        )

    def run(self) -> CrawlResult:
        collected_at = as_seoul(self.config.now or datetime.now(UTC))
        cursor = Cursor.load(self.config.cursor_path, self.config)
        already = set(cursor.collected_ids)
        resumed_count = len(already)
        identity_path = identity_path_for(self.config.cursor_path)
        identity = PostingIdentityStore.load(identity_path, source_site=SOURCE_SITE)
        identity_known_before = len(identity)
        new_postings = 0
        updated_changed_content = 0
        skipped_same_content = 0

        records: list[JobPostingInput] = []
        body_status_counts: Counter[str] = Counter()
        date_label_counts: Counter[str] = Counter()
        category_counts: Counter[str] = Counter()
        technology_mention_count = 0
        rows_seen = 0
        skipped_out_of_range = 0
        skipped_resumed = 0
        skipped_undated = 0
        detail_errors: list[dict[str, str]] = []
        invalid_records: list[dict[str, str]] = []
        stopped_reason: str | None = None
        pages_read = 0
        pages_by_category: dict[str, int] = {}
        # Every row id this run has seen, across categories. A posting tagged
        # into both H0 and N0 appears in both listings, and fetching its
        # detail twice would double the request count for no new data.
        seen_row_ids: set[str] = set()
        duplicate_rows = 0

        for category in self.config.categories:
            if stopped_reason is not None:
                break
            name = JOB_CATEGORIES[category]
            self._progress(f"직종 {category} ({name})")

            for page in range(1, self.config.max_pages + 1):
                try:
                    items, date_labels = self._fetch_list_page(
                        category, page, now=collected_at
                    )
                except BlockedError as error:
                    stopped_reason = f"blocked: {error}"
                    self._progress(f"{category} page {page}: blocked, stopping")
                    break
                except HttpError as error:
                    stopped_reason = f"list fetch failed: {error}"
                    self._progress(f"{category} page {page}: {error}")
                    break

                pages_read += 1
                pages_by_category[category] = page
                date_label_counts.update(date_labels)

                if not items:
                    # Real rows ran out. The ad slots the parser discards are
                    # why this is the stop condition rather than a link count.
                    self._progress(f"{category} page {page}: no rows, listing exhausted")
                    break

                rows_seen += len(items)
                new_ids = {item.source_posting_id for item in items} - seen_row_ids
                duplicate_rows += len(items) - len(new_ids)
                seen_row_ids |= new_ids
                self._progress(
                    f"{category} page {page}: {len(items)} rows, {len(new_ids)} new"
                )

                for item in items:
                    if item.source_posting_id in already:
                        skipped_resumed += 1
                        continue
                    if item.posted_on is None:
                        # No server-side range filter, so an undated row
                        # cannot be assumed to be in range.
                        skipped_undated += 1
                        continue
                    if not self._in_range(item.posted_on):
                        skipped_out_of_range += 1
                        continue

                    try:
                        detail, detail_error = self._fetch_detail(item)
                    except BlockedError as error:
                        stopped_reason = f"blocked on detail: {error}"
                        self._progress(f"detail {item.source_posting_id}: blocked")
                        break
                    if detail_error:
                        detail_errors.append(
                            {
                                "posting_id": item.source_posting_id,
                                "error": detail_error,
                            }
                        )

                    record, invalid = self._build_record(
                        item, detail, detail_error, collected_at
                    )
                    if invalid is not None:
                        invalid_records.append(invalid)
                        continue

                    assert record is not None

                    # The cursor above only knows ids, so it cannot tell a
                    # posting that was re-listed unchanged from one whose body
                    # moved. That needs the content hash, and the hash needs
                    # the detail page — so this decision is made after the
                    # fetch, not at the listing.
                    decision = identity.record(
                        item.source_posting_id, record.content_hash
                    )

                    # The cursor claims the posting either way: within this
                    # date range it has been dealt with, and re-fetching it in
                    # a resumed run would only reach the same conclusion.
                    already.add(item.source_posting_id)
                    cursor.collected_ids.append(item.source_posting_id)

                    if decision is Decision.UNCHANGED:
                        skipped_same_content += 1
                        continue
                    if decision is Decision.CHANGED:
                        updated_changed_content += 1
                    else:
                        new_postings += 1

                    records.append(record)
                    body_status_counts[record.body_status.value] += 1
                    technology_mention_count += len(record.technology_mentions)
                    category_counts[category] += 1

                # Advanced in memory only. Persisting here is what made an
                # interrupted run lose postings permanently — the cursor
                # claimed them while the batch had not been written yet, so a
                # resume skipped them silently. `write_outputs` persists it
                # after the batch is on disk (S15P21E102-174).
                cursor.last_page = page

                if stopped_reason is not None:
                    break
                # Deliberately no early stop on an out-of-range page: the
                # listing is not ordered by registration date. Measured
                # 2026-09-09, page 2 of H0 was older than page 1.

        pipeline_run_id = pipeline_run_id_for(SOURCE_SITE, collected_at)
        batch = JobAnalysisInputBatch(
            schema_version=JOB_ANALYSIS_INPUT_SCHEMA_VERSION,
            dataset_snapshot_id=dataset_snapshot_id_for(
                SOURCE_SITE,
                self.config.start_date,
                self.config.end_date,
            ),
            pipeline_run_id=pipeline_run_id,
            collector_version=COLLECTOR_VERSION,
            records=tuple(records),
        )

        manifest: dict[str, Any] = {
            "source_site": SOURCE_SITE,
            "collector_version": COLLECTOR_VERSION,
            "schema_version": JOB_ANALYSIS_INPUT_SCHEMA_VERSION,
            "pipeline_run_id": pipeline_run_id,
            "dataset_snapshot_id": batch.dataset_snapshot_id,
            "collected_at": collected_at.isoformat(),
            # Recorded in every run's manifest, not only in a doc: a batch
            # that outlives this repository still says on what basis it was
            # collected. See the module docstring.
            "source_admission": {
                "criterion_a": "FAIL",
                "operator": "(주)커리어넷 220-86-73547",
                "robots_txt": "allows the posting paths (job.career.co.kr)",
                "terms_clause": (
                    "이용약관 제14조 5항 — 동의없이 복제·배포 금지 "
                    "(제20조 6·7항 동일 취지)"
                ),
                "admitted_by": "project owner decision, 2026-09-09",
                "note": (
                    "기준 A 는 OR 조건이므로 robots.txt 허용만으로는 통과가 "
                    "아니다. 약관 조항을 확인한 뒤 소유자가 진행을 결정했다."
                ),
            },
            "request": {
                "base_url": self.config.base_url,
                "list_path": LIST_PATH,
                "start_date": self.config.start_date.isoformat(),
                "end_date": self.config.end_date.isoformat(),
                "categories": [
                    {"code": code, "name": JOB_CATEGORIES[code]}
                    for code in self.config.categories
                ],
                "category_preset": self.config.category_preset,
                "listing_page_size": self.config.page_size,
                "listing_sort": LISTING_SORT,
                "max_pages": self.config.max_pages,
                "request_delay_seconds": self.config.request_delay,
                "fetch_detail": self.config.fetch_detail,
                "server_side_filtering": True,
                "server_side_filtering_note": (
                    "i_jc1 (직종 대분류) filters server-side and page advances "
                    "for real: pages 2 and 3 of H0 shared no posting ids "
                    "(2026-09-09). Registration date has no server-side "
                    "filter and the listing is not ordered by it, so the date "
                    "range is applied per row and no page ends the run early."
                ),
            },
            "counts": {
                "records": len(records),
                "pages_read": pages_read,
                "pages_by_category": pages_by_category,
                "rows_seen": rows_seen,
                # `rows_seen` counts rows; a posting tagged into two 대분류
                # appears twice. These make the gap explicit rather than
                # letting a reader take rows for postings.
                "distinct_postings_seen": len(seen_row_ids),
                "duplicate_rows": duplicate_rows,
                "records_by_category": dict(sorted(category_counts.items())),
                "skipped_out_of_range": skipped_out_of_range,
                "skipped_already_collected": skipped_resumed,
                # `records` is new + updated; a skipped_same_content posting was
                # fetched and judged, not collected, so it is counted apart.
                "new_postings": new_postings,
                "updated_changed_content": updated_changed_content,
                "skipped_same_content": skipped_same_content,
                "skipped_undated": skipped_undated,
                "detail_errors": len(detail_errors),
                "invalid_records": len(invalid_records),
            },
            # 등록 vs 수정. A posting dated by its modification date is not
            # wrong to collect, but the run should say how many there were.
            "listing_date_labels": dict(sorted(date_label_counts.items())),
            "technology_extraction": {
                "method": "RULE_BASED_V1",
                "mention_count": technology_mention_count,
                "requirement_types": ["REQUIRED", "PREFERRED", "MENTIONED"],
                # The site's `span.otNm` 직종 tags are kept in
                # `raw_job_category` as the site's own text. They are not
                # promoted to technology mentions: there is no SourceSurface
                # for a site tag, and one measured Product Owner posting
                # carried 웹프로그래머 and 응용프로그래머 tags.
                "site_category_tags_stored_as": "raw_job_category",
            },
            "body_status_counts": dict(sorted(body_status_counts.items())),
            "resume": {
                "cursor_path": (
                    str(self.config.cursor_path) if self.config.cursor_path else None
                ),
                "ids_known_before_run": resumed_count,
                "ids_known_after_run": len(already),
            },
            # Separate from `resume` on purpose: resume is scoped to this run's
            # date range and resets with it, identity is not and does not.
            "identity": {
                "identity_path": str(identity_path) if identity_path else None,
                "postings_known_before_run": identity_known_before,
                "postings_known_after_run": len(identity),
            },
            "stopped_reason": stopped_reason,
            "detail_error_samples": detail_errors[:20],
            "invalid_record_samples": invalid_records[:20],
        }
        return CrawlResult(
            batch=batch,
            manifest=manifest,
            cursor=cursor,
            cursor_path=self.config.cursor_path,
            identity=identity,
            identity_path=identity_path,
        )

    def _in_range(self, posted_on: date) -> bool:
        return self.config.start_date <= posted_on <= self.config.end_date

    def _build_record(
        self,
        item: ListingRow,
        detail,
        detail_error: str | None,
        collected_at: datetime,
    ) -> tuple[JobPostingInput | None, dict[str, str] | None]:
        """Hand the parsed page to the shared normalizer (S15P21E102-99)."""

        deadline_label = (
            detail.deadline_label
            if detail and detail.deadline_label
            else item.deadline_label
        )
        try:
            record = normalize_posting(
                source_site=SOURCE_SITE,
                row=item,
                detail=detail,
                source_url=self.client.absolute(item.detail_ref),
                collected_at=collected_at,
                detail_fetched=self.config.fetch_detail,
                deadline_date=parse_deadline(
                    deadline_label, today=self.config.end_date
                ),
                detail_error=detail_error,
            )
        except ValidationError as error:
            return None, {
                "posting_id": item.source_posting_id,
                "error": error.errors(include_url=False).__str__()[:800],
            }
        return record, None


CSV_FIELDS = [
    "source_record_id",
    "source_site",
    "source_posting_id",
    "source_url",
    "company_name",
    "title",
    "raw_job_category",
    "career_level",
    "region",
    "body_status",
    "posting_status",
    "posted_at",
    "deadline",
    "collected_at",
    "content_hash",
    "description_char_count",
    "technology_mentions",
]


def write_outputs(result: CrawlResult, output_dir: Path) -> dict[str, Path]:
    """Write the validated JSON batch, an analyst CSV, and a run manifest."""

    run_dir = output_dir / result.batch.pipeline_run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    json_path = run_dir / "job_analysis_input.json"
    csv_path = run_dir / "postings.csv"
    manifest_path = run_dir / "manifest.json"

    _atomic_write(
        json_path,
        result.batch.model_dump_json(by_alias=True, indent=2) + "\n",
    )

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for record in result.batch.records:
        writer.writerow(
            {
                "source_record_id": record.source_record_id,
                "source_site": record.source_site,
                "source_posting_id": record.source_posting_id,
                "source_url": str(record.source_url),
                "company_name": record.company_name,
                "title": record.title,
                "raw_job_category": record.raw_job_category or "",
                "career_level": record.career_level or "",
                "region": record.region or "",
                "body_status": record.body_status.value,
                "posting_status": record.posting_status.value,
                "posted_at": record.posted_at.isoformat() if record.posted_at else "",
                "deadline": record.deadline.isoformat() if record.deadline else "",
                "collected_at": record.collected_at.isoformat(),
                "content_hash": record.content_hash,
                "description_char_count": len(record.description_text or ""),
                "technology_mentions": json.dumps(
                    sorted(
                        {
                            mention.source_technology_id
                            for mention in record.technology_mentions
                            if mention.source_technology_id
                        }
                    ),
                    ensure_ascii=False,
                ),
            }
        )
    _atomic_write(csv_path, buffer.getvalue())

    manifest = dict(result.manifest)
    manifest["outputs"] = {
        "job_analysis_input.json": json_path.name,
        "postings.csv": csv_path.name,
        "manifest.json": manifest_path.name,
    }
    manifest["output_sha256"] = {
        json_path.name: hashlib.sha256(json_path.read_bytes()).hexdigest()
    }
    _atomic_write(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    # Last, and only here. The cursor asserts these postings are collected,
    # which is only true now that the batch above is on disk. Writing it any
    # earlier turns an interrupted run into permanent loss, because a resume
    # trusts the cursor and skips them without reporting anything.
    if result.cursor is not None:
        result.cursor.save(result.cursor_path)
    # Same rule, same reason: a posting is only "seen" once its batch exists.
    if result.identity is not None:
        result.identity.save(result.identity_path)

    return {"json": json_path, "csv": csv_path, "manifest": manifest_path}


def _atomic_write(path: Path, content: str) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)
    os.replace(temp_path, path)


def _parse_cli_date(value: str) -> date:
    return date.fromisoformat(value)


def _categories(explicit: str | None, preset: str | None) -> tuple[str, ...]:
    """Merge an explicit 대분류 list with a preset, preserving order."""

    codes = list(CATEGORY_PRESETS[preset]) if preset else []
    codes += [code.strip().upper() for code in (explicit or "").split(",") if code.strip()]
    if not codes:
        codes = list(CATEGORY_PRESETS["dev"])
    return tuple(dict.fromkeys(codes))


def build_arg_parser() -> argparse.ArgumentParser:
    today = datetime.now(UTC).date()
    parser = argparse.ArgumentParser(
        prog="python -m Career_Collector_V1",
        description=(
            "Collect 커리어 postings registered in a date range and write a "
            "job-analysis-input/v1 batch."
        ),
    )
    parser.add_argument("--start-date", default=today.isoformat())
    parser.add_argument("--end-date", default=today.isoformat())
    parser.add_argument(
        "--days-back",
        type=int,
        default=0,
        help="widen the range to N days before --end-date (for scheduled runs)",
    )
    parser.add_argument("--output-dir", default="data/career")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--page-size", type=int, default=LISTING_PAGE_SIZE)
    parser.add_argument(
        "--request-delay",
        type=float,
        default=DEFAULT_REQUEST_DELAY,
        help="seconds to wait between requests",
    )
    parser.add_argument(
        "--no-detail",
        action="store_true",
        help="list-only smoke run; records get body_status=MISSING",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--no-upload-raw",
        action="store_true",
        help=(
            "skip the HDFS Raw upload; by default a run publishes to Raw "
            "whenever WEBHDFS_URL is set (see job/collector/raw_sink.py)"
        ),
    )
    parser.add_argument(
        "--cursor",
        default=None,
        help="resume-state file; omit to collect without resume support",
    )
    parser.add_argument(
        "--category",
        default=None,
        help=(
            "comma-separated 직종 대분류 codes; "
            + ", ".join(f"{code}={name}" for code, name in JOB_CATEGORIES.items())
        ),
    )
    parser.add_argument(
        "--category-preset",
        default=None,
        choices=sorted(CATEGORY_PRESETS),
        help="named 대분류 set; combined with --category when both given",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        end_date = _parse_cli_date(args.end_date)
        start_date = _parse_cli_date(args.start_date)
        if args.days_back < 0:
            raise ValueError("--days-back must not be negative")
        if args.days_back:
            start_date = end_date - timedelta(days=args.days_back)
        config = CrawlConfig(
            start_date=start_date,
            end_date=end_date,
            categories=_categories(args.category, args.category_preset),
            category_preset=args.category_preset,
            max_pages=args.max_pages,
            page_size=args.page_size,
            request_delay=args.request_delay,
            fetch_detail=not args.no_detail,
            base_url=args.base_url,
            cursor_path=Path(args.cursor) if args.cursor else None,
        )
    except ValueError as error:
        print(f"invalid arguments: {error}", file=sys.stderr)
        return 2

    crawler = CareerCrawler(
        config,
        on_progress=lambda message: print(message, file=sys.stderr),
    )
    result = crawler.run()
    paths = write_outputs(result, Path(args.output_dir))

    counts = result.manifest["counts"]
    print(
        f"records={counts['records']} "
        f"pages={counts['pages_read']} "
        f"invalid={counts['invalid_records']} "
        f"detail_errors={counts['detail_errors']}"
    )
    print(f"json={paths['json']}")
    print(f"manifest={paths['manifest']}")

    if not args.no_upload_raw:
        sink = sink_from_env()
        if sink is None:
            print("raw=skipped (WEBHDFS_URL 미설정)", file=sys.stderr)
        else:
            upload = sink.upload_run(
                paths["manifest"].parent,
                source=SOURCE_SITE,
                collected_at=result.batch.records[0].collected_at
                if result.batch.records
                else datetime.now(UTC),
                pipeline_run_id=result.batch.pipeline_run_id,
            )
            write_upload_record(paths["manifest"].parent, upload)
            print(f"raw={upload.run_path}")
            for entry in upload.failed:
                print(
                    f"raw failed: {entry['file']} - {entry['error']}", file=sys.stderr
                )
            if not upload.ok:
                # The local snapshot is intact; a Raw failure must be visible
                # to the scheduler without discarding what was collected.
                return 1

            # S15P21E102-220. Raw keeps every run; `analysis_input` keeps only
            # the ones C may compute on, so the publisher re-checks the
            # manifest and refuses an early stop, detail failures, invalid
            # records or an empty run. A refusal is a normal outcome and does
            # not fail the collection.
            published = publish_from_env(
                paths["manifest"].parent,
                source=SOURCE_SITE,
                pipeline_run_id=result.batch.pipeline_run_id,
            )
            if published is None:
                print("analysis_input=skipped (WEBHDFS_URL 미설정)", file=sys.stderr)
            elif published.skipped:
                print(
                    f"analysis_input=skipped ({', '.join(published.blockers)})",
                    file=sys.stderr,
                )
            else:
                print(f"analysis_input={published.run_path}")
                for entry in published.failed:
                    print(
                        f"analysis_input failed: {entry['file']} - {entry['error']}",
                        file=sys.stderr,
                    )
                if not published.ok:
                    # Raw already holds the run, so this is reported rather
                    # than retried here.
                    return 1

    if result.manifest["stopped_reason"]:
        print(f"stopped: {result.manifest['stopped_reason']}", file=sys.stderr)
    return collector_exit_code(result.manifest, source_site=SOURCE_SITE)
