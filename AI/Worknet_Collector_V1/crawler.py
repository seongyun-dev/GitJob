"""Worknet backend-posting collector.

Emits a `job-analysis-input/v1` batch (see `AI/job/contracts.py`), which is
the authoritative A-to-C contract. Nothing here defines or extends that
contract; a record that fails validation is reported, not repaired.

Postings cannot be collected retroactively, so a run keeps whatever it has
already validated even when a later page fails, and records the failure in
the manifest.
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
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from job.collector import (
    ListingRow,
    dataset_snapshot_id_for,
    normalize_posting,
    pipeline_run_id_for,
)
from job.collector.raw_sink import sink_from_env, write_upload_record
from job.contracts import (
    JOB_ANALYSIS_INPUT_SCHEMA_VERSION,
    JobAnalysisInputBatch,
    JobPostingInput,
)

from .client import (
    DEFAULT_BASE_URL,
    WorknetBlockedError,
    WorknetHttpClient,
    WorknetHttpError,
)
from .dates import as_seoul, date_range_bounds, parse_cli_date, parse_date
from .occupations import OCCUPATION_PRESETS, resolve_occupation_preset
from .parser import DetailContent, parse_detail, parse_job_list

COLLECTOR_VERSION = "worknet-collector/v1"
# Uppercase to match the source_site convention in the S15P21E102-90
# fixture (JOBKOREA / JOBPLANET / SARAMIN / WANTED).
SOURCE_SITE = "WORKNET"
LIST_PATH = "/wk/a/b/1200/retriveDtlEmpSrchList.do"

DEFAULT_PAGE_SIZE = 50
DEFAULT_MAX_PAGES = 20
DEFAULT_REQUEST_DELAY = 1.0

# Verified against the live listing on 2026-09-07. Values left empty are the
# site's own "no filter" defaults; only the keys in `_page_params` change per
# request. Do not prune keys without re-checking the listing: Worknet's search
# action rejects partially populated parameter sets.
_LIST_PARAM_TEMPLATE: tuple[tuple[str, str], ...] = (
    ("searchOn", "Y"),
    ("termSearchGbn", "all"),
    ("siteClcd", "all"),
    ("cloTermSearchGbn", "all"),
    ("enterPriseGbn", "all"),
    ("academicGbnoEdu", "noEdu"),
    ("benefitSrchAndOr", "O"),
    ("listCookieInfo", "DTL"),
    ("sortField", "DATE"),
    ("sortFieldInfo", "DATE"),
    ("sortOrderBy", "DESC"),
    ("sortOrderByInfo", "DESC"),
)


class CollectionStopped(RuntimeError):
    """Collection for this site stopped early; partial results are kept."""


@dataclass(frozen=True)
class CrawlConfig:
    start_date: date
    end_date: date
    page_size: int = DEFAULT_PAGE_SIZE
    max_pages: int = DEFAULT_MAX_PAGES
    request_delay: float = DEFAULT_REQUEST_DELAY
    fetch_detail: bool = True
    base_url: str = DEFAULT_BASE_URL
    region_code: str | None = None
    cursor_path: Path | None = None
    # Free-text search. Verified against the live listing: "개발자" returns
    # developer postings where an unfiltered run returns none.
    keyword: str | None = None
    # Worknet 직종 codes for the `occupation` filter. The code list is not
    # published on the search page; `occupations.py` records it, the endpoint
    # it came from, and the named presets (`dev` is the development set).
    occupation_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        date_range_bounds(self.start_date, self.end_date)
        if self.page_size < 1:
            raise ValueError("page_size must be positive")
        if self.max_pages < 1:
            raise ValueError("max_pages must be positive")
        if self.request_delay < 0:
            raise ValueError("request_delay must not be negative")


@dataclass
class Cursor:
    """Resume state for one site.

    Worknet has no stable offset, so the cursor stores the posting ids already
    validated in this date range. Re-running skips them instead of emitting a
    second record for the same posting.
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
            # A different range: the stored ids say nothing about this run.
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


ProgressCallback = Callable[[str], None]


class WorknetCrawler:
    def __init__(
        self,
        config: CrawlConfig,
        client: WorknetHttpClient | None = None,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self.config = config
        self.client = client or WorknetHttpClient(base_url=config.base_url)
        self._on_progress = on_progress

    def _progress(self, message: str) -> None:
        if self._on_progress is not None:
            self._on_progress(message)

    def _page_params(self, page: int) -> list[tuple[str, str]]:
        params = list(_LIST_PARAM_TEMPLATE)
        params += [
            ("resultCnt", str(self.config.page_size)),
            ("resultCntInfo", str(self.config.page_size)),
            ("currntPageNo", str(page)),
            ("pageIndex", str(page)),
            ("regDateStdt", self.config.start_date.strftime("%Y%m%d")),
            ("regDateEndt", self.config.end_date.strftime("%Y%m%d")),
        ]
        if self.config.region_code:
            params += [
                ("codeDepth1Info", self.config.region_code),
                ("codeDepth2Info", self.config.region_code),
            ]
        if self.config.keyword:
            params += [
                ("keyword", self.config.keyword),
                ("srcKeyword", self.config.keyword),
            ]
        if self.config.occupation_codes:
            # The site's own script joins the picker selections into one
            # comma-separated value before submitting.
            params.append(("occupation", ",".join(self.config.occupation_codes)))
        return params

    def _fetch_list_page(self, page: int) -> list[ListingRow]:
        html = self.client.get(
            LIST_PATH,
            self._page_params(page),
            delay_seconds=self.config.request_delay if page > 1 else 0.0,
        )
        return parse_job_list(html)

    def _fetch_detail(
        self, item: ListingRow
    ) -> tuple[DetailContent | None, str | None]:
        if not self.config.fetch_detail:
            # Not an error: --no-detail is a deliberate list-only run, and
            # `_build_record` already maps that to body_status=MISSING.
            # Reporting it as a detail error made a clean smoke run print
            # "detail_errors=10".
            return None, None
        referer = self.client.absolute(LIST_PATH)
        try:
            html = self.client.get(
                item.detail_ref,
                referer=referer,
                delay_seconds=self.config.request_delay,
            )
        except WorknetBlockedError:
            raise
        except WorknetHttpError as error:
            return None, str(error)
        try:
            return parse_detail(html), None
        except Exception as error:  # noqa: BLE001 - parser must not abort a run
            return None, f"detail parse failed: {error}"

    def run(self) -> CrawlResult:
        collected_at = as_seoul(datetime.now(UTC))
        cursor = Cursor.load(self.config.cursor_path, self.config)
        already = set(cursor.collected_ids)
        resumed_count = len(already)

        records: list[JobPostingInput] = []
        body_status_counts: Counter[str] = Counter()
        technology_mention_count = 0
        skipped_out_of_range = 0
        skipped_resumed = 0
        detail_errors: list[dict[str, str]] = []
        invalid_records: list[dict[str, str]] = []
        stopped_reason: str | None = None
        pages_read = 0

        for page in range(1, self.config.max_pages + 1):
            try:
                items = self._fetch_list_page(page)
            except WorknetBlockedError as error:
                stopped_reason = f"blocked: {error}"
                self._progress(f"page {page}: blocked, stopping this site")
                break
            except WorknetHttpError as error:
                stopped_reason = f"list fetch failed: {error}"
                self._progress(f"page {page}: {error}")
                break

            pages_read = page
            if not items:
                self._progress(f"page {page}: no rows, listing exhausted")
                break

            self._progress(f"page {page}: {len(items)} rows")
            page_in_range = 0

            for item in items:
                if not self._in_range(item.posted_on):
                    skipped_out_of_range += 1
                    continue
                page_in_range += 1
                if item.source_posting_id in already:
                    skipped_resumed += 1
                    continue

                try:
                    detail, detail_error = self._fetch_detail(item)
                except WorknetBlockedError as error:
                    stopped_reason = f"blocked on detail: {error}"
                    self._progress("detail blocked, stopping this site")
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
                records.append(record)
                body_status_counts[record.body_status.value] += 1
                technology_mention_count += len(record.technology_mentions)
                already.add(item.source_posting_id)
                cursor.collected_ids.append(item.source_posting_id)

            cursor.last_page = page
            cursor.save(self.config.cursor_path)

            if stopped_reason is not None:
                break
            # Listing is sorted by registration date descending, so a page with
            # nothing in range means everything after it is older.
            if page_in_range == 0:
                self._progress(f"page {page}: all rows older than start date")
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
            "request": {
                "base_url": self.config.base_url,
                "list_path": LIST_PATH,
                "start_date": self.config.start_date.isoformat(),
                "end_date": self.config.end_date.isoformat(),
                "page_size": self.config.page_size,
                "max_pages": self.config.max_pages,
                "request_delay_seconds": self.config.request_delay,
                "fetch_detail": self.config.fetch_detail,
                "region_code": self.config.region_code,
                "keyword": self.config.keyword,
                "occupation_codes": list(self.config.occupation_codes),
            },
            "counts": {
                "records": len(records),
                "pages_read": pages_read,
                "skipped_out_of_range": skipped_out_of_range,
                "skipped_already_collected": skipped_resumed,
                "detail_errors": len(detail_errors),
                "invalid_records": len(invalid_records),
            },
            "technology_extraction": {
                "method": "RULE_BASED_V1",
                "mention_count": technology_mention_count,
                "requirement_types": [
                    "REQUIRED",
                    "PREFERRED",
                    "MENTIONED",
                ],
            },
            "body_status_counts": dict(sorted(body_status_counts.items())),
            "resume": {
                "cursor_path": (
                    str(self.config.cursor_path) if self.config.cursor_path else None
                ),
                "ids_known_before_run": resumed_count,
                "ids_known_after_run": len(already),
            },
            "stopped_reason": stopped_reason,
            "detail_error_samples": detail_errors[:20],
            "invalid_record_samples": invalid_records[:20],
        }
        return CrawlResult(batch=batch, manifest=manifest)

    def _in_range(self, posted_on: date | None) -> bool:
        if posted_on is None:
            # Keep undated rows: the server-side range filter already applied,
            # and dropping them would silently lose postings.
            return True
        return self.config.start_date <= posted_on <= self.config.end_date

    def _build_record(
        self,
        item: ListingRow,
        detail: DetailContent | None,
        detail_error: str | None,
        collected_at: datetime,
    ) -> tuple[JobPostingInput | None, dict[str, str] | None]:
        """Hand the parsed page to the shared normalizer.

        Everything this used to do by hand now lives in
        `job.collector.normalize` (S15P21E102-99): body-status resolution,
        the content hash, posting status, and the registration-date fallback.
        Two hand-written copies had already drifted apart — Worknet emitted no
        technology mentions at all, because the extractor sat in the JobKorea
        package.

        What stays here is the part that needs the site: resolving relative
        URLs against this run's base URL, and Worknet's own deadline-label
        format.
        """

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
                deadline_date=parse_date(deadline_label),
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
        detail: DetailContent | None,
    ) -> DetailContent | None:
        """Resolve image sources before the normalizer sees them.

        The normalizer puts the first image straight into `raw_artifact_uri`
        for an IMAGE_ONLY record, so it must already be absolute — it has no
        base URL to resolve against and must not guess a host.
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
    "career_level",
    "region",
    "body_status",
    "posting_status",
    "posted_at",
    "deadline",
    "collected_at",
    "content_hash",
    "description_char_count",
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
                "career_level": record.career_level or "",
                "region": record.region or "",
                "body_status": record.body_status.value,
                "posting_status": record.posting_status.value,
                "posted_at": record.posted_at.isoformat() if record.posted_at else "",
                "deadline": record.deadline.isoformat() if record.deadline else "",
                "collected_at": record.collected_at.isoformat(),
                "content_hash": record.content_hash,
                "description_char_count": len(record.description_text or ""),
            }
        )
    _atomic_write(csv_path, buffer.getvalue())

    manifest = dict(result.manifest)
    manifest["outputs"] = {
        "job_analysis_input.json": json_path.name,
        "postings.csv": csv_path.name,
        "manifest.json": manifest_path.name,
    }
    _atomic_write(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )

    return {"json": json_path, "csv": csv_path, "manifest": manifest_path}


def _atomic_write(path: Path, content: str) -> None:
    """Write via a temp file, without newline translation.

    `newline=""` matters on Windows: the CSV writer already emits CRLF, and
    letting text mode translate again produces CR CR LF, which readers see as
    a blank line between every row.
    """

    temp_path = path.with_name(path.name + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)
    os.replace(temp_path, path)


def build_arg_parser() -> argparse.ArgumentParser:
    today = datetime.now(UTC).date()
    parser = argparse.ArgumentParser(
        prog="python -m Worknet_Collector_V1",
        description=(
            "Collect Worknet postings registered in a date range and write a "
            "job-analysis-input/v1 batch."
        ),
    )
    parser.add_argument("--start-date", default=today.isoformat())
    parser.add_argument(
        "--end-date",
        default=today.isoformat(),
        help="inclusive end of the registration-date range",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=0,
        help=(
            "widen the range to N days before --end-date; a scheduled run needs "
            "this because postings registered late yesterday carry yesterday's "
            "date and a today-only window would never see them"
        ),
    )
    parser.add_argument("--output-dir", default="data/worknet")
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
        "--region-code",
        default=None,
        help="Worknet region code (codeDepth1Info); omit for no region filter",
    )
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
        "--keyword",
        default=None,
        help='free-text job search, e.g. "개발자"; omit to collect all jobs',
    )
    parser.add_argument(
        "--occupation",
        default=None,
        help=(
            "comma-separated Worknet 직종 codes for the occupation filter; "
            "see occupations.py for the code list and where it came from"
        ),
    )
    parser.add_argument(
        "--occupation-preset",
        default=None,
        choices=sorted(OCCUPATION_PRESETS),
        help="named 직종 code set; combined with --occupation when both given",
    )
    return parser


def _occupation_codes(
    explicit: str | None,
    preset: str | None,
) -> tuple[str, ...]:
    """Merge an explicit code list with a preset, preserving order.

    Both are accepted together so a run can take a preset and add one leaf
    code without spelling the whole set out.
    """

    codes = list(resolve_occupation_preset(preset)) if preset else []
    codes += [code.strip() for code in (explicit or "").split(",") if code.strip()]
    return tuple(dict.fromkeys(codes))


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        end_date = parse_cli_date(args.end_date)
        start_date = parse_cli_date(args.start_date)
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
            region_code=args.region_code,
            cursor_path=Path(args.cursor) if args.cursor else None,
            keyword=args.keyword,
            occupation_codes=_occupation_codes(
                args.occupation,
                args.occupation_preset,
            ),
        )
    except ValueError as error:
        print(f"invalid arguments: {error}", file=sys.stderr)
        return 2

    crawler = WorknetCrawler(
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
                print(f"raw failed: {entry['file']} - {entry['error']}", file=sys.stderr)
            if not upload.ok:
                # The local snapshot is intact; a Raw failure must be visible
                # to the scheduler without discarding what was collected.
                return 1

    if result.manifest["stopped_reason"]:
        print(f"stopped: {result.manifest['stopped_reason']}", file=sys.stderr)
        return 1 if counts["records"] == 0 else 0
    return 0 if counts["records"] else 1
