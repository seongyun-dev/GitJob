"""Saramin job-posting collector (S15P21E102-148).

Emits a `job-analysis-input/v1` batch (`AI/job/contracts.py`), mapped by the
shared normalizer from S15P21E102-99. Nothing here defines or extends the
contract; a record that fails validation is reported, not repaired.

### robots.txt

Saramin disallows the ordinary posting-detail paths for `User-agent: *`
(`/zf_user/recruit/view/`, `/zf_user/recruit/recruit-posting/`,
`/recruit/recruit_view.php`) and explicitly allows
`/zf_user/jobs/view/popup`. This collector requests the allowed popup, which
serves the same 상세요강 body, and never the disallowed paths. The search
listing path is not disallowed. See the README before adding a request.

### No server-side date range

Unlike Worknet, the search has no registration-date parameter that this
collector relies on. Instead the listing is requested with `recruitSort=reg_dt`
and rows outside the range are dropped, and paging stops once a page contains
nothing in range — the ordering is what makes that safe.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
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

from .categories import CATEGORY_PRESETS, resolve_category_preset
from .dates import as_seoul, parse_deadline
from .parser import SaraminDetail, listing_date_labels, parse_detail, parse_job_list

COLLECTOR_VERSION = "saramin-collector/v2"
# Uppercase to match the source_site convention in the S15P21E102-90 fixture.
SOURCE_SITE = "SARAMIN"
DEFAULT_BASE_URL = "https://www.saramin.co.kr"
LIST_PATH = "/zf_user/search/recruit"

DEFAULT_PAGE_SIZE = 50
DEFAULT_MAX_PAGES = 20
# Saramin is a commercial site with no API grant for us yet (S15P21E102-161 is
# submitted and waiting), so the interval is deliberately slower than
# Worknet's public-sector listing.
DEFAULT_REQUEST_DELAY = 2.0


@dataclass(frozen=True)
class CrawlConfig:
    start_date: date
    end_date: date
    page_size: int = DEFAULT_PAGE_SIZE
    max_pages: int = DEFAULT_MAX_PAGES
    request_delay: float = DEFAULT_REQUEST_DELAY
    fetch_detail: bool = True
    base_url: str = DEFAULT_BASE_URL
    cursor_path: Path | None = None
    keyword: str | None = None
    # Saramin 직군 codes for `cat_kewd`. See categories.py: role codes only,
    # never stack codes.
    category_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        if self.page_size < 1:
            raise ValueError("page_size must be positive")
        if self.max_pages < 1:
            raise ValueError("max_pages must be positive")
        if self.request_delay < 0:
            raise ValueError("request_delay must not be negative")


@dataclass
class Cursor:
    """Resume state for this site.

    The search has no stable offset either, so the cursor stores the posting
    ids already validated in this date range and a re-run skips them.
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
    # failure that cost Saramin 2,337 postings on 2026-09-08 and 296 more on
    # 2026-09-09 (S15P21E102-174). Defaulted so a caller building a result by
    # hand simply gets no resume state.
    cursor: Cursor | None = None
    cursor_path: Path | None = None
    # Cross-run identity, persisted next to the cursor and for the same reason:
    # only once the batch is on disk. The cursor forgets its ids the moment the
    # run's date range moves; this store carries no range and does not.
    identity: PostingIdentityStore | None = None
    identity_path: Path | None = None


ProgressCallback = Callable[[str], None]


class SaraminCrawler:
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

    def _page_params(self, page: int) -> list[tuple[str, str]]:
        params = [
            # Registration order is what makes the client-side range filter
            # and the early stop safe; without it a page of old postings could
            # end collection while newer ones are still unseen.
            ("recruitSort", "reg_dt"),
            ("recruitPage", str(page)),
            ("recruitPageCount", str(self.config.page_size)),
        ]
        if self.config.category_codes:
            params.append(("cat_kewd", ",".join(self.config.category_codes)))
        if self.config.keyword:
            params += [("searchword", self.config.keyword), ("searchType", "search")]
        return params

    def _fetch_list_page(self, page: int) -> tuple[list[ListingRow], list[str]]:
        html = self.client.get(
            LIST_PATH,
            self._page_params(page),
            delay_seconds=self.config.request_delay if page > 1 else 0.0,
        )
        return (
            parse_job_list(html, today=self.config.end_date),
            listing_date_labels(html),
        )

    def _fetch_detail(
        self, item: ListingRow
    ) -> tuple[SaraminDetail | None, str | None]:
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
            return parse_detail(html, today=self.config.end_date), None
        except Exception as error:  # noqa: BLE001 - parser must not abort a run
            return None, f"detail parse failed: {error}"

    def run(self) -> CrawlResult:
        collected_at = as_seoul(datetime.now(UTC))
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
        technology_mention_count = 0
        skipped_out_of_range = 0
        skipped_resumed = 0
        skipped_undated = 0
        detail_errors: list[dict[str, str]] = []
        invalid_records: list[dict[str, str]] = []
        stopped_reason: str | None = None
        pages_read = 0

        for page in range(1, self.config.max_pages + 1):
            try:
                items, date_labels = self._fetch_list_page(page)
            except BlockedError as error:
                stopped_reason = f"blocked: {error}"
                self._progress(f"page {page}: blocked, stopping this site")
                break
            except HttpError as error:
                stopped_reason = f"list fetch failed: {error}"
                self._progress(f"page {page}: {error}")
                break

            pages_read = page
            date_label_counts.update(date_labels)
            if not items:
                self._progress(f"page {page}: no rows, listing exhausted")
                break

            self._progress(f"page {page}: {len(items)} rows")
            page_in_range = 0

            for item in items:
                if item.posted_on is None:
                    # Unlike Worknet there is no server-side range filter, so
                    # an undated row cannot be assumed to be in range.
                    skipped_undated += 1
                    continue
                if not self._in_range(item.posted_on):
                    skipped_out_of_range += 1
                    continue
                page_in_range += 1
                if item.source_posting_id in already:
                    skipped_resumed += 1
                    continue

                try:
                    detail, detail_error = self._fetch_detail(item)
                except BlockedError as error:
                    stopped_reason = f"blocked on detail: {error}"
                    self._progress(f"detail {item.source_posting_id}: blocked")
                    break
                if detail_error:
                    detail_errors.append(
                        {"posting_id": item.source_posting_id, "error": detail_error}
                    )

                record, invalid = self._build_record(
                    item, detail, detail_error, collected_at
                )
                if invalid is not None:
                    invalid_records.append(invalid)
                    continue

                assert record is not None

                # The cursor above only knows ids, so it cannot tell a posting
                # that was re-listed unchanged from one whose body moved. That
                # distinction needs the content hash, and the hash needs the
                # detail page — so this decision is made here, after the fetch.
                decision = identity.record(
                    item.source_posting_id, record.content_hash
                )

                # The cursor claims the posting either way: within this date
                # range it has been dealt with, and re-fetching it in a resumed
                # run would only spend a request to reach the same conclusion.
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

            # Advanced in memory only. Persisting here is what made an
            # interrupted run lose postings permanently — the cursor claimed
            # them while the batch had not been written yet, so a resume
            # skipped them silently. `write_outputs` persists it instead,
            # after the batch is on disk (S15P21E102-174).
            cursor.last_page = page

            if stopped_reason is not None:
                break
            # Sorted by registration date descending, so a page with nothing
            # in range means everything after it is older.
            if page_in_range == 0:
                self._progress(f"page {page}: all rows outside the date range")
                break

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
            "robots": {
                "detail_path": "/zf_user/jobs/view/popup",
                "note": "robots.txt Allow; the ordinary detail paths are Disallow",
            },
            "request": {
                "base_url": self.config.base_url,
                "list_path": LIST_PATH,
                "start_date": self.config.start_date.isoformat(),
                "end_date": self.config.end_date.isoformat(),
                "page_size": self.config.page_size,
                "max_pages": self.config.max_pages,
                "request_delay_seconds": self.config.request_delay,
                "fetch_detail": self.config.fetch_detail,
                "keyword": self.config.keyword,
                "category_codes": list(self.config.category_codes),
            },
            "counts": {
                "records": len(records),
                "pages_read": pages_read,
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
            # 등록일 vs 수정일. A posting dated by its modification date is
            # not wrong to collect, but the run should say how many there were.
            "listing_date_labels": dict(sorted(date_label_counts.items())),
            "technology_extraction": {
                "method": "RULE_BASED_V1",
                "mention_count": technology_mention_count,
                "requirement_types": ["REQUIRED", "PREFERRED", "MENTIONED"],
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
        detail: SaraminDetail | None,
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
                detail=self._with_absolute_assets(detail),
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

    def _with_absolute_assets(
        self,
        detail: SaraminDetail | None,
    ) -> SaraminDetail | None:
        """Resolve image sources before the normalizer sees them.

        The normalizer puts the first image straight into `raw_artifact_uri`
        for an IMAGE_ONLY record, so it must already be absolute.
        """

        if detail is None or not detail.image_sources:
            return detail
        return replace(
            detail,
            image_sources=tuple(
                self.client.absolute(source) for source in detail.image_sources
            ),
        )


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

    batch_text = result.batch.model_dump_json(by_alias=True, indent=2) + "\n"
    _atomic_write(json_path, batch_text)

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
    manifest["output_sha256"] = {
        json_path.name: sha256(batch_text.encode("utf-8")).hexdigest()
    }
    manifest["outputs"] = {
        "job_analysis_input.json": json_path.name,
        "postings.csv": csv_path.name,
        "manifest.json": manifest_path.name,
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


def _category_codes(explicit: str | None, preset: str | None) -> tuple[str, ...]:
    """Merge an explicit code list with a preset, preserving order."""

    codes = list(resolve_category_preset(preset)) if preset else []
    codes += [code.strip() for code in (explicit or "").split(",") if code.strip()]
    return tuple(dict.fromkeys(codes))


def build_arg_parser() -> argparse.ArgumentParser:
    today = datetime.now(UTC).date()
    parser = argparse.ArgumentParser(
        prog="python -m Saramin_Collector_V1",
        description=(
            "Collect Saramin postings registered in a date range and write a "
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
    parser.add_argument("--output-dir", default="data/saramin")
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
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
        "--keyword", default=None, help='free-text search, e.g. "개발자"'
    )
    parser.add_argument(
        "--category",
        default=None,
        help="comma-separated Saramin cat_kewd 직군 codes; see categories.py",
    )
    parser.add_argument(
        "--category-preset",
        default=None,
        choices=sorted(CATEGORY_PRESETS),
        help="named 직군 code set; combined with --category when both given",
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
            page_size=args.page_size,
            max_pages=args.max_pages,
            request_delay=args.request_delay,
            fetch_detail=not args.no_detail,
            base_url=args.base_url,
            cursor_path=Path(args.cursor) if args.cursor else None,
            keyword=args.keyword,
            category_codes=_category_codes(args.category, args.category_preset),
        )
    except ValueError as error:
        print(f"invalid arguments: {error}", file=sys.stderr)
        return 2

    crawler = SaraminCrawler(
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
        return 1 if counts["records"] == 0 else 0
    return 0 if counts["records"] else 1
