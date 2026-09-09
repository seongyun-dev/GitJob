"""게임잡 job-posting collector.

Emits a `job-analysis-input/v1` batch (`AI/job/contracts.py`), mapped by the
shared normalizer from S15P21E102-99 and published to HDFS Raw by
`job.collector.raw_sink`. Nothing here defines or extends the contract; a
record that fails validation is reported, not repaired.

Kafka is deliberately absent. S15P21E102-103 publishes `jobs.collected` from
the scheduler (`job/collector/__main__.py`) once a round's Raw upload has
succeeded, and the event is a Claim Check carrying the run location rather
than the postings. A per-crawler producer would either duplicate that or turn
one round into one message per posting, so this collector only has to be
declared in `schedule.toml` to be announced.

### robots.txt

`https://www.gamejob.co.kr/robots.txt`, read 2026-09-08, disallows
`/List_GG/`, `/Login/`, `/User/`, `/Text_User/`, `/Text_Co/`, `/Project/`,
`/Help/` and `/Corp/Person/Find` for `User-agent: *`.

This collector requests `/List_Gi/GI_Total_List.asp` and `/Recruit/…`, neither
of which is disallowed. **`/List_GG/GG_Total_List.asp` is linked from the site
header and is disallowed** — it is close enough in name to the path used here
that it is worth stating: do not switch to it. `/Project/` (프로젝트·외주) is
also disallowed, so freelance listings are out of scope for this collector.

### No server-side filtering, so paging cannot stop early

Saramin sorts by `recruitSort=reg_dt` and stops once a page holds nothing in
range. That is not available here. Verified on 2026-09-08: `?orderTab=3`
(등록일순), `?psTab=40` and `?duty=1` all return a page byte-identical to the
unfiltered request — those controls POST into a server-side session and the
listing is re-rendered from it.

**`?Page=N` is ignored too.** Measured 2026-09-08: 80 pages returned 3,200
rows holding **40 distinct postings** — every page is the same page. So the
whole listing reachable over the query string is those 40, and `--max-pages`
buys requests rather than data. `run` therefore stops as soon as a page
contributes no new posting id (see `seen_row_ids`), which turns a
`--max-pages 10` run from 10 list requests into 2.

The real pagination lives behind the session-scoped `/recruit/_GI_Job_List`
fragment, which returned 0 bytes on repeated attempts and is not used.

Two further consequences, both deliberate:

- **A page with no in-range rows does not end the run.** The default order is
  추천순, so an older row can be followed by a newer one. Stopping on that
  would silently drop postings — the failure S15P21E102-107 exists to
  prevent. Only a page with no *new* postings ends it.
- **The 직무 filter runs on our side**, from the listing's tracking call, and
  only to avoid a detail fetch. See `duties.py`.

### A posting costs up to three requests

The body is in iframes (`parser.body_iframe_refs`), so 담당업무 and 자격조건
are one fetch each on top of the detail page. That is the reason the default
request delay is not lowered to match Worknet's public-sector listing.
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
from job.collector.http import BlockedError, HttpError, PoliteHttpClient
from job.collector.raw_sink import sink_from_env, write_upload_record
from job.contracts import (
    JOB_ANALYSIS_INPUT_SCHEMA_VERSION,
    JobAnalysisInputBatch,
    JobPostingInput,
)

from .dates import as_seoul, parse_deadline
from .duties import DUTY_PRESETS, matches_preset, resolve_duty_preset
from .parser import (
    GameJobDetail,
    body_iframe_refs,
    listing_date_labels,
    parse_body_fragment,
    parse_detail,
    parse_job_list,
)

COLLECTOR_VERSION = "gamejob-collector/v2"
# Uppercase to match the source_site convention in the S15P21E102-90 fixture.
SOURCE_SITE = "GAMEJOB"
DEFAULT_BASE_URL = "https://www.gamejob.co.kr"
# `/List_Gi/` — not the disallowed `/List_GG/`. See the module docstring.
LIST_PATH = "/List_Gi/GI_Total_List.asp"

# The listing serves 40 rows per page and `psTab` does not change it over the
# query string, so this is an observation, not a setting.
LISTING_PAGE_SIZE = 40
DEFAULT_MAX_PAGES = 20
# 게임잡 is a commercial site with no API grant, and one posting costs up to
# three requests, so the interval matches Saramin's rather than Worknet's.
DEFAULT_REQUEST_DELAY = 2.0
# A posting body is 담당업무 + 자격조건. The cap stops a restructured page that
# renders a dozen iframes from turning one posting into a dozen requests.
DEFAULT_MAX_BODY_SECTIONS = 4


@dataclass(frozen=True)
class CrawlConfig:
    start_date: date
    end_date: date
    max_pages: int = DEFAULT_MAX_PAGES
    request_delay: float = DEFAULT_REQUEST_DELAY
    fetch_detail: bool = True
    base_url: str = DEFAULT_BASE_URL
    cursor_path: Path | None = None
    max_body_sections: int = DEFAULT_MAX_BODY_SECTIONS
    # 모집분야 tokens for the client-side pre-filter. Empty collects every
    # 직무 the listing carries.
    duty_tokens: tuple[str, ...] = ()
    duty_preset: str | None = None
    # Fixed clock. The listing dates rows relative to the present ("3시간 전
    # 등록"), so a test with fixture markup needs to pin "now" to stay
    # deterministic. Same override JobKorea's CrawlConfig carries.
    now: datetime | None = None

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        if self.max_pages < 1:
            raise ValueError("max_pages must be positive")
        if self.request_delay < 0:
            raise ValueError("request_delay must not be negative")
        if self.max_body_sections < 1:
            raise ValueError("max_body_sections must be positive")


@dataclass
class Cursor:
    """Resume state for this site.

    The listing has no stable offset — the default order is 추천순 — so the
    cursor stores the posting ids already validated in this date range and a
    re-run skips them. Same shape as Saramin's for the same reason.
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


ProgressCallback = Callable[[str], None]


class GameJobCrawler:
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

    def _fetch_list_page(
        self,
        page: int,
        *,
        now: datetime,
    ) -> tuple[list[ListingRow], list[str]]:
        html = self.client.get(
            LIST_PATH,
            [("Page", str(page))],
            delay_seconds=self.config.request_delay if page > 1 else 0.0,
        )
        return (
            parse_job_list(html, now=now),
            listing_date_labels(html, now=now),
        )

    def _fetch_detail(
        self,
        item: ListingRow,
    ) -> tuple[GameJobDetail | None, str | None]:
        """Fetch the detail page and the iframes holding its body."""

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
            refs = body_iframe_refs(html)
        except Exception as error:  # noqa: BLE001 - parser must not abort a run
            return None, f"detail parse failed: {error}"

        detail_url = self.client.absolute(item.detail_ref)
        sections: list[str] = []
        images: list[str] = []
        body_errors: list[str] = []

        for name, src in refs[: self.config.max_body_sections]:
            try:
                fragment = self.client.get(
                    src,
                    referer=detail_url,
                    delay_seconds=self.config.request_delay,
                )
            except BlockedError:
                raise
            except HttpError as error:
                body_errors.append(f"{name or src}: {error}")
                continue
            try:
                text, fragment_images = parse_body_fragment(fragment)
            except Exception as error:  # noqa: BLE001 - as above
                body_errors.append(f"{name or src}: parse failed: {error}")
                continue
            if text:
                # The heading is part of how the page reads, and it is the
                # site's own text, so it is kept as the block's label rather
                # than concatenating 담당업무 and 자격조건 into one wall.
                sections.append(f"{name}\n{text}" if name else text)
            images.extend(fragment_images)

        detail = replace(
            detail,
            description_text="\n\n".join(sections) or None,
            image_sources=tuple(
                dict.fromkeys(self.client.absolute(src) for src in images)
            ),
        )
        # A body error is only worth reporting when it cost us the body. With
        # text in hand the run is fine, and the section count already shows
        # that one block is missing.
        if body_errors and detail.description_text is None:
            return detail, "; ".join(body_errors)[:400]
        return detail, None

    def run(self) -> CrawlResult:
        collected_at = as_seoul(self.config.now or datetime.now(UTC))
        cursor = Cursor.load(self.config.cursor_path, self.config)
        already = set(cursor.collected_ids)
        resumed_count = len(already)

        records: list[JobPostingInput] = []
        body_status_counts: Counter[str] = Counter()
        date_label_counts: Counter[str] = Counter()
        technology_mention_count = 0
        site_keyword_count = 0
        rows_seen = 0
        skipped_out_of_range = 0
        skipped_resumed = 0
        skipped_undated = 0
        skipped_out_of_preset = 0
        kept_unknown_category = 0
        detail_errors: list[dict[str, str]] = []
        invalid_records: list[dict[str, str]] = []
        stopped_reason: str | None = None
        pages_read = 0
        # Every row id this run has seen, filtered or not. Deliberately not
        # the cursor's `already` set: that holds only *collected* ids, so a
        # page whose new postings are all out of range or out of preset would
        # look like "nothing new" and end the run with pages still unread.
        seen_row_ids: set[str] = set()
        duplicate_rows = 0

        for page in range(1, self.config.max_pages + 1):
            try:
                items, date_labels = self._fetch_list_page(page, now=collected_at)
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

            rows_seen += len(items)
            new_ids = {item.source_posting_id for item in items} - seen_row_ids
            duplicate_rows += len(items) - len(new_ids)
            seen_row_ids |= new_ids
            self._progress(f"page {page}: {len(items)} rows, {len(new_ids)} new")

            # Rows arrived but every one of them was already seen, so `Page`
            # is not advancing the listing. Measured 2026-09-08: 80 pages
            # returned 3,200 rows holding 40 distinct postings — the `.asp`
            # listing ignores `Page` exactly as it ignores `orderTab`,
            # `psTab` and `duty`. Continuing only repeats requests against a
            # site this collector is trying not to be blocked by.
            #
            # `stopped_reason` is deliberately left unset. Every 게임잡 run
            # ends here, so recording it as a stop reason would mark each one
            # abnormal, print to stderr, and travel into the `jobs.collected`
            # payload — the same reason `listing exhausted` above sets nothing.
            # The manifest carries it as a diagnostic instead.
            if page > 1 and not new_ids:
                self._progress(f"page {page}: no new postings, paging is inert")
                break

            for item in items:
                if item.posted_on is None:
                    # There is no server-side range filter, so an undated row
                    # cannot be assumed to be in range.
                    skipped_undated += 1
                    continue
                if not self._in_range(item.posted_on):
                    skipped_out_of_range += 1
                    continue
                if item.source_posting_id in already:
                    skipped_resumed += 1
                    continue

                verdict = self._preset_verdict(item)
                if verdict is False:
                    skipped_out_of_preset += 1
                    continue
                if verdict is None and self.config.duty_tokens:
                    # 모집분야 unreadable on the row. Kept and counted — a
                    # dropped posting can never be collected again, while an
                    # extra detail fetch only costs a request.
                    kept_unknown_category += 1

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
                records.append(record)
                body_status_counts[record.body_status.value] += 1
                technology_mention_count += len(record.technology_mentions)
                if detail is not None:
                    site_keyword_count += len(detail.keywords)
                already.add(item.source_posting_id)
                cursor.collected_ids.append(item.source_posting_id)

            # Advanced in memory only. Persisting here is what made an
            # interrupted run lose postings permanently — the cursor claimed
            # them while the batch had not been written yet, so a resume
            # skipped them silently. `write_outputs` persists it instead,
            # after the batch is on disk (S15P21E102-174).
            cursor.last_page = page

            if stopped_reason is not None:
                break
            # Deliberately no early stop on an out-of-range page: the listing
            # is not ordered by registration date. See the module docstring.

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
                "list_path": LIST_PATH,
                "detail_path": "/Recruit/GI_Read/View",
                "note": (
                    "robots.txt Disallow: /List_GG/, /Project/, /User/, /Help/ "
                    "— none requested. /List_Gi/ and /Recruit/ are allowed."
                ),
            },
            "request": {
                "base_url": self.config.base_url,
                "list_path": LIST_PATH,
                "start_date": self.config.start_date.isoformat(),
                "end_date": self.config.end_date.isoformat(),
                "listing_page_size": LISTING_PAGE_SIZE,
                "max_pages": self.config.max_pages,
                "request_delay_seconds": self.config.request_delay,
                "fetch_detail": self.config.fetch_detail,
                "max_body_sections": self.config.max_body_sections,
                "duty_preset": self.config.duty_preset,
                "duty_tokens": list(self.config.duty_tokens),
                "server_side_filtering": False,
                "server_side_filtering_note": (
                    "orderTab/psTab/duty/Page are all session-scoped and "
                    "ignored as query parameters: 80 pages returned 3,200 "
                    "rows holding 40 distinct postings (2026-09-08). The run "
                    "stops once a page adds no new posting id, and 직무 is "
                    "filtered client-side."
                ),
                "paging_advances": len(seen_row_ids) > LISTING_PAGE_SIZE,
            },
            "counts": {
                "records": len(records),
                "pages_read": pages_read,
                "rows_seen": rows_seen,
                # `rows_seen` is rows, not postings. 게임잡 repeats the same
                # page for every `Page` value, so the two diverge sharply and
                # reading `rows_seen` as a posting count overstates coverage
                # by the page count. These make the gap explicit.
                "distinct_postings_seen": len(seen_row_ids),
                "duplicate_rows": duplicate_rows,
                "skipped_out_of_range": skipped_out_of_range,
                "skipped_already_collected": skipped_resumed,
                "skipped_undated": skipped_undated,
                "skipped_out_of_preset": skipped_out_of_preset,
                "kept_unknown_category": kept_unknown_category,
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
                # The site's own 키워드 tags, counted but not stored: there is
                # no SourceSurface for a site tag. See parser.py.
                "site_keyword_count": site_keyword_count,
                "site_keywords_stored": False,
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
        return CrawlResult(
            batch=batch,
            manifest=manifest,
            cursor=cursor,
            cursor_path=self.config.cursor_path,
        )

    def _in_range(self, posted_on: date) -> bool:
        return self.config.start_date <= posted_on <= self.config.end_date

    def _preset_verdict(self, item: ListingRow) -> bool | None:
        """Is this row in the requested 직무 preset?

        True when it matches, False when it does not, None when the row does
        not say. With no preset configured everything matches.
        """

        if not self.config.duty_tokens:
            return True
        return matches_preset(item.raw_job_category, self.config.duty_tokens)

    def _build_record(
        self,
        item: ListingRow,
        detail: GameJobDetail | None,
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

    return {"json": json_path, "csv": csv_path, "manifest": manifest_path}


def _atomic_write(path: Path, content: str) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)
    os.replace(temp_path, path)


def _parse_cli_date(value: str) -> date:
    return date.fromisoformat(value)


def _duty_tokens(explicit: str | None, preset: str | None) -> tuple[str, ...]:
    """Merge an explicit 모집분야 list with a preset, preserving order."""

    tokens = list(resolve_duty_preset(preset)) if preset else []
    tokens += [token.strip() for token in (explicit or "").split(",") if token.strip()]
    return tuple(dict.fromkeys(tokens))


def build_arg_parser() -> argparse.ArgumentParser:
    today = datetime.now(UTC).date()
    parser = argparse.ArgumentParser(
        prog="python -m GameJob_Collector_V1",
        description=(
            "Collect 게임잡 postings registered in a date range and write a "
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
    parser.add_argument("--output-dir", default="data/gamejob")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument(
        "--request-delay",
        type=float,
        default=DEFAULT_REQUEST_DELAY,
        help="seconds to wait between requests",
    )
    parser.add_argument(
        "--max-body-sections",
        type=int,
        default=DEFAULT_MAX_BODY_SECTIONS,
        help="body iframes to fetch per posting",
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
        "--duty",
        default=None,
        help="comma-separated 모집분야 tokens; see duties.py",
    )
    parser.add_argument(
        "--duty-preset",
        default=None,
        choices=sorted(DUTY_PRESETS),
        help="named 모집분야 token set; combined with --duty when both given",
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
            max_pages=args.max_pages,
            request_delay=args.request_delay,
            fetch_detail=not args.no_detail,
            base_url=args.base_url,
            cursor_path=Path(args.cursor) if args.cursor else None,
            max_body_sections=args.max_body_sections,
            duty_tokens=_duty_tokens(args.duty, args.duty_preset),
            duty_preset=args.duty_preset,
        )
    except ValueError as error:
        print(f"invalid arguments: {error}", file=sys.stderr)
        return 2

    crawler = GameJobCrawler(
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

    if result.manifest["stopped_reason"]:
        print(f"stopped: {result.manifest['stopped_reason']}", file=sys.stderr)
        return 1 if counts["records"] == 0 else 0
    return 0 if counts["records"] else 1
