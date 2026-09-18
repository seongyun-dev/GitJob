"""JobKorea backend-posting crawler and A-to-C batch writer."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin

from pydantic import ValidationError

from job.collector import dataset_snapshot_id_for, pipeline_run_id_for
from job.collector.analysis_input import publish_from_env
from job.collector.raw_sink import sink_from_env, write_upload_record
from job.collector.raw_verify import verify_run
from job.contracts import (
    JOB_ANALYSIS_INPUT_SCHEMA_VERSION,
    BodyStatus,
    JobAnalysisInputBatch,
    JobPostingInput,
)

from .adapter import SOURCE_SITE, normalize_jobkorea_posting
from .client import (
    JobKoreaBlockedError,
    JobKoreaHttpClient,
    JobKoreaHttpError,
)
from .dates import SEOUL, as_seoul, date_range_bounds, parse_deadline, parse_posted_at
from .duties import DutyScope, resolve_duty_preset
from .ocr import (
    OcrRecognitionError,
    OcrUnavailableError,
    PaddleOcrEngine,
    image_suffix,
)
from .parser import DetailContent, JobListItem, parse_detail, parse_job_list


class CollectionMode(StrEnum):
    """What a run is selecting, which is also what its output means.

    ``DATE_RANGE`` reads pages ordered by registration date and keeps the rows
    inside the requested window. ``ACTIVE_LISTING`` (S15P21E102-335) ignores
    the window and takes every posting the site still lists for a duty scope,
    which is a different population and therefore a different contract.
    """

    DATE_RANGE = "date_range"
    ACTIVE_LISTING = "active_listing"


# One version per mode, never one constant for both. `job.jobkorea_contract`
# and `job.collector.analysis_input` admit a snapshot as the fixed 16-duty v3
# population only when the version says v3, so a legacy date-range batch
# wearing that stamp would be handed to v3 validation -- and an active-scope
# batch stamped v2 would be refused by it.
COLLECTOR_VERSION_DATE_RANGE = "jobkorea-crawler/v2"
COLLECTOR_VERSION_ACTIVE_LISTING = "jobkorea-crawler/v3"

_COLLECTOR_VERSIONS = {
    CollectionMode.DATE_RANGE: COLLECTOR_VERSION_DATE_RANGE,
    CollectionMode.ACTIVE_LISTING: COLLECTOR_VERSION_ACTIVE_LISTING,
}


def collector_version_for(mode: CollectionMode) -> str:
    """Resolve the collector version a mode is allowed to stamp."""

    try:
        return _COLLECTOR_VERSIONS[mode]
    except KeyError:  # pragma: no cover - guards a future mode addition
        raise ValueError(f"no collector version declared for mode {mode!r}") from None


# Must stay equal to `_TERMINAL_SCOPE_REASONS` in `job.jobkorea_contract`: the
# consumer decides a scope finished from the reason this producer writes, so a
# reason outside this set is how the producer says "not complete". The contract
# test in `tests/test_jobkorea_v3_active.py` pins the two together.
TERMINAL_SCOPE_REASONS = frozenset({"short_page", "empty_page"})


def _aggregate_scan_stop_reason(scope_reasons: list[dict[str, str]]) -> str:
    """Reduce per-scope outcomes to the run's single reason.

    A one-scope run reports that scope's reason, which is what the legacy
    date-range manifest has always carried. A multi-scope run may only say
    ``all_scopes_complete`` when every scope ended on a terminal reason --
    otherwise it reports a non-terminal one, so neither the run nor any scope
    can look finished when a scope never answered.
    """

    reasons = [scope["scan_stop_reason"] for scope in scope_reasons]
    if not reasons:  # pragma: no cover - `scan_scopes` is never empty
        return "max_pages"
    if len(reasons) == 1:
        return reasons[0]
    if all(reason in TERMINAL_SCOPE_REASONS for reason in reasons):
        return "all_scopes_complete"
    if "first_page_empty" in reasons:
        return "first_page_empty"
    return "max_pages"


DEFAULT_BASE_URL = "https://www.jobkorea.co.kr"
DEFAULT_DUTY_CODE = "1000229"
DEFAULT_DUTY_NAME = "백엔드개발자"
ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class CrawlConfig:
    """Runtime options. ``end_date`` is inclusive for user-facing CLI clarity."""

    start_date: date
    end_date: date
    output_dir: Path = Path("data/jobkorea")
    base_url: str = DEFAULT_BASE_URL
    duty_code: str = DEFAULT_DUTY_CODE
    duty_name: str = DEFAULT_DUTY_NAME
    max_pages: int = 100
    page_size: int = 40
    # 2.0 for both, matching 워크넷·사람인·게임잡·커리어. These were 0.8 and
    # 0.5 while this collector was a one-shot August backfill run by hand.
    # S15P21E102-196 put it on a twice-daily schedule, and this is the site
    # with the adjudicated precedent against crawling — the least defensible
    # place in the project to be the fastest requester.
    request_delay: float = 2.0
    detail_delay: float = 2.0
    timeout: float = 30.0
    max_attempts: int = 3
    fetch_details: bool = True
    ocr_images: bool = True
    ocr_device: str = "cpu"
    ocr_min_confidence: float = 0.35
    max_images_per_posting: int = 20
    user_agent: str = "GitJob-JobKoreaCrawler/0.1"
    cursor_path: Path | None = None
    now: datetime | None = None
    collection_mode: CollectionMode = CollectionMode.DATE_RANGE
    duty_scopes: tuple[DutyScope, ...] = ()

    @property
    def collector_version(self) -> str:
        """The only place a run's collector version is decided."""

        return collector_version_for(self.collection_mode)

    @property
    def scan_scopes(self) -> tuple[DutyScope, ...]:
        """The scopes to scan, with the legacy single-duty run as one scope.

        Expressing the legacy shape as a one-element tuple keeps a single scan
        loop, so the date-range path cannot drift away from the active-scope
        path as the latter grows.
        """

        if self.duty_scopes:
            return self.duty_scopes
        return (
            DutyScope(
                code=self.duty_code,
                name=self.duty_name,
                target_role="",
            ),
        )

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if self.max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        if self.page_size < 1:
            raise ValueError("page_size must be at least 1")
        if self.request_delay < 0 or self.detail_delay < 0:
            raise ValueError("request delays must not be negative")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if not self.ocr_device.strip():
            raise ValueError("ocr_device must not be blank")
        if not 0 <= self.ocr_min_confidence <= 1:
            raise ValueError("ocr_min_confidence must be between 0 and 1")
        if self.max_images_per_posting < 1:
            raise ValueError("max_images_per_posting must be at least 1")


@dataclass
class Cursor:
    """Resume state for this site (S15P21E102-196).

    The listing is sorted by registration date but offers no stable offset, so
    the cursor stores the posting ids already written for this date range and a
    re-run skips them. Same shape as 사람인·게임잡·커리어 for the same reason.

    A different range resets it: `load` returns fresh state when either bound
    moved, so widening `--days-back` re-collects rather than silently trusting
    ids gathered under other bounds.
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
    # `write_outputs` saves the cursor last, after the batch and the manifest
    # are on disk, so it can never claim postings whose batch was never
    # stored — S15P21E102-174.
    cursor: Cursor | None = None
    cursor_path: Path | None = None


class JobKoreaCrawler:
    """Collect a date-bounded category slice from JobKorea."""

    def __init__(
        self,
        config: CrawlConfig,
        client: JobKoreaHttpClient | None = None,
    ) -> None:
        self.config = config
        self.client = client or JobKoreaHttpClient(
            base_url=config.base_url,
            timeout=config.timeout,
            max_attempts=config.max_attempts,
            user_agent=config.user_agent,
        )

    @property
    def list_url(self) -> str:
        query = urlencode(
            {
                "menucode": "duty",
                "duty": self.config.duty_code,
            }
        )
        return f"{self.config.base_url.rstrip('/')}/Recruit/JobList?{query}"

    def detail_url(self, posting_id: str) -> str:
        query = urlencode(
            {
                "Gno": posting_id,
                "isHiringCenter": "false",
                "hideMapView": "false",
            }
        )
        return f"{self.config.base_url.rstrip('/')}/Recruit/GI_Read_Comt_Ifrm?{query}"

    def _list_request_data(
        self,
        page: int,
        *,
        duty_code: str | None = None,
    ) -> list[tuple[str, str]]:
        return [
            ("condition[menucode]", "duty"),
            ("condition[duty]", duty_code or self.config.duty_code),
            ("page", str(page)),
            ("direct", "0"),
            ("order", "2"),
            ("pagesize", str(self.config.page_size)),
            ("tabindex", "0"),
            ("onePick", "0"),
            ("confirm", "0"),
            ("profile", "0"),
        ]

    def _fetch_list_page(
        self,
        page: int,
        *,
        duty_code: str | None = None,
    ) -> list[JobListItem]:
        html = self.client.post(
            "/Recruit/Home/_GI_List/",
            self._list_request_data(page, duty_code=duty_code),
            referer=self.list_url,
            delay_seconds=self.config.request_delay,
        )
        return parse_job_list(html, self.config.base_url)

    def _ocr_images(
        self,
        row: JobListItem,
        image_sources: tuple[str, ...],
        engine: PaddleOcrEngine,
    ) -> tuple[str, dict[str, Any], list[str]]:
        resolved_sources = self._resolve_image_sources(row, image_sources)
        limited_sources = resolved_sources[: self.config.max_images_per_posting]
        errors: list[str] = []
        recognized_texts: list[str] = []
        confidences: list[float] = []
        processed_count = 0

        for image_url in limited_sources:
            try:
                image_bytes = self.client.get_bytes(
                    image_url,
                    referer=row.source_url,
                    delay_seconds=self.config.detail_delay,
                )
                result = engine.recognize_bytes(
                    image_bytes,
                    suffix=image_suffix(image_url),
                )
                processed_count += 1
                if result.text:
                    recognized_texts.append(result.text)
                if result.average_confidence is not None:
                    confidences.append(result.average_confidence)
            except (JobKoreaHttpError, OcrRecognitionError) as error:
                errors.append(f"{image_url}: {type(error).__name__}: {error}")
            except Exception as error:  # noqa: BLE001
                errors.append(f"{image_url}: {type(error).__name__}: {error}")

        recognized_text = "\n".join(recognized_texts).strip()
        if recognized_text and not errors:
            status = "COMPLETED"
        elif recognized_text:
            status = "PARTIAL"
        else:
            status = "FAILED"
        metadata: dict[str, Any] = {
            "posting_id": row.posting_id,
            "status": status,
            "image_urls": limited_sources,
            "image_count": len(limited_sources),
            "images_processed": processed_count,
            "images_failed": len(errors),
            "recognized_chars": len(recognized_text),
            "average_confidence": (
                round(sum(confidences) / len(confidences), 4) if confidences else None
            ),
            "errors": errors,
        }
        if len(resolved_sources) > len(limited_sources):
            metadata["truncated_image_count"] = len(resolved_sources) - len(
                limited_sources
            )
        return recognized_text, metadata, errors

    def _resolve_image_sources(
        self,
        row: JobListItem,
        image_sources: tuple[str, ...],
    ) -> list[str]:
        resolved_sources: list[str] = []
        seen_sources: set[str] = set()
        for source in image_sources:
            resolved = urljoin(row.source_url, source)
            if resolved not in seen_sources:
                seen_sources.add(resolved)
                resolved_sources.append(resolved)
        return resolved_sources

    def run(self, progress_callback: ProgressCallback | None = None) -> CrawlResult:
        collected_at = as_seoul(self.config.now or datetime.now(tz=SEOUL))
        start_at, end_exclusive = date_range_bounds(
            self.config.start_date,
            self.config.end_date,
        )
        warnings: list[str] = []
        seen_ids: set[str] = set()
        # Keyed by posting id: one posting listed under several duty scopes is
        # one posting. The 2026-09-15 run saw 9,128 raw rows for 5,859 distinct
        # postings, so this is the difference between the two numbers.
        selected_by_id: dict[str, tuple[JobListItem, datetime | None]] = {}
        stats: Counter[str] = Counter()
        cursor = Cursor.load(self.config.cursor_path, self.config)
        already = set(cursor.collected_ids)
        active_listing = self.config.collection_mode is CollectionMode.ACTIVE_LISTING
        scopes = self.config.scan_scopes
        scope_reasons: list[dict[str, str]] = []
        total_page_budget = len(scopes) * self.config.max_pages

        for scope_index, scope in enumerate(scopes):
            scope_reason = "max_pages"
            for page in range(1, self.config.max_pages + 1):
                _notify_progress(
                    progress_callback,
                    {
                        "stage": "list",
                        "current": scope_index * self.config.max_pages + page,
                        "total": total_page_budget,
                        "message": f"{scope.name} 목록 페이지 {page} 수집 중",
                    },
                )
                rows = self._fetch_list_page(page, duty_code=scope.code)
                stats["pages_scanned"] += 1
                stats["raw_rows_seen"] += len(rows)
                if not rows:
                    if page == 1:
                        # An empty *first* page is not an exhausted list. It is
                        # a scope that never answered -- blocked, or re-skinned
                        # so the parser reads nothing. The legacy single-scope
                        # run has nothing left to do and keeps raising; a v3
                        # run records a deliberately non-terminal reason so the
                        # other 15 scopes still run while this snapshot can
                        # never claim `all_scopes_complete`.
                        if not active_listing:
                            raise JobKoreaHttpError(
                                "JobKorea list response contained no parseable postings"
                            )
                        scope_reason = "first_page_empty"
                        warnings.append(
                            f"{scope.name}: first list page returned no parseable "
                            "postings; scope is incomplete"
                        )
                        break
                    scope_reason = "empty_page"
                    break

                page_dates: list[datetime] = []
                unknown_date_count = 0
                for row in rows:
                    posted_at = parse_posted_at(
                        row.posted_label,
                        now=collected_at,
                        default_year=self.config.start_date.year,
                    )
                    if posted_at is None:
                        unknown_date_count += 1
                    else:
                        page_dates.append(posted_at)

                    if row.posting_id in seen_ids:
                        stats["duplicates_skipped"] += 1
                        if row.posting_id in selected_by_id:
                            stats["cross_scope_duplicates"] += 1
                        continue
                    seen_ids.add(row.posting_id)
                    stats["unique_rows_seen"] += 1
                    # Active-scope selection is "the site still lists it",
                    # which is why an unreadable registration label does not
                    # drop the posting here.
                    in_window = (
                        posted_at is not None and start_at <= posted_at < end_exclusive
                    )
                    if active_listing or in_window:
                        # Skipped before the detail request, which is the point:
                        # a resumed run must not re-fetch a posting it already
                        # wrote. The date shortcut below still reads every page's
                        # labels, so skipping here cannot end the scan early.
                        if row.posting_id in already:
                            stats["skipped_already_collected"] += 1
                            continue
                        selected_by_id[row.posting_id] = (row, posted_at)

                if unknown_date_count:
                    warnings.append(
                        f"{scope.name} page {page}: {unknown_date_count} row(s) had "
                        "an unparsed registration label"
                    )

                # The POST request is explicitly sorted by registration date. Once a
                # complete page is older than the requested range, later pages are
                # outside the range as well. Unknown labels disable this shortcut.
                # An active-scope run wants the whole list, so it does not stop
                # at the window.
                if (
                    not active_listing
                    and len(page_dates) == len(rows)
                    and page_dates
                    and max(page_dates) < start_at
                ):
                    scope_reason = "before_start_date"
                    break
                if len(rows) < self.config.page_size:
                    scope_reason = "short_page"
                    break
            else:
                boundary = "listing terminal page" if active_listing else "date boundary"
                warnings.append(
                    f"{scope.name}: max_pages reached before the {boundary} "
                    "was observed"
                )
            scope_reasons.append(
                {
                    "code": scope.code,
                    "name": scope.name,
                    "target_role": scope.target_role,
                    "scan_stop_reason": scope_reason,
                }
            )

        scan_stop_reason = _aggregate_scan_stop_reason(scope_reasons)
        selected = list(selected_by_id.values())

        if not self.config.fetch_details:
            warnings.append(
                "detail fetching disabled; records have body_status=MISSING"
            )
        ocr_enabled = self.config.fetch_details and self.config.ocr_images
        if self.config.ocr_images and not self.config.fetch_details:
            warnings.append("OCR skipped because detail fetching is disabled")

        records: list[JobPostingInput] = []
        detail_failures: list[dict[str, str]] = []
        invalid_records: list[dict[str, str]] = []
        body_status_counts: Counter[str] = Counter()
        posting_status_counts: Counter[str] = Counter()
        ocr_stats: Counter[str] = Counter()
        ocr_records: list[dict[str, Any]] = []
        ocr_engine: PaddleOcrEngine | None = None
        ocr_unavailable = False
        technology_mention_count = 0

        detail_total = len(selected)
        for detail_index, (row, posted_at) in enumerate(selected, start=1):
            _notify_progress(
                progress_callback,
                {
                    "stage": "detail",
                    "current": detail_index,
                    "total": detail_total,
                    "message": f"상세 공고 {detail_index}/{detail_total} 처리 중",
                },
            )
            detail: DetailContent | None = None
            body_status = BodyStatus.MISSING
            detail_error: str | None = None
            if self.config.fetch_details:
                stats["detail_requests"] += 1
                try:
                    detail_html = self.client.get(
                        self.detail_url(row.posting_id),
                        referer=row.source_url,
                        delay_seconds=self.config.detail_delay,
                    )
                    detail = parse_detail(detail_html)
                    body_status = BodyStatus(detail.body_status)
                except JobKoreaBlockedError as error:
                    body_status = BodyStatus.BLOCKED
                    detail_error = str(error)
                except JobKoreaHttpError as error:
                    body_status = BodyStatus.BLOCKED
                    detail_error = str(error)
                except Exception as error:  # noqa: BLE001
                    body_status = BodyStatus.PARSE_FAILED
                    detail_error = f"{type(error).__name__}: {error}"

            description_text = detail.description_text if detail else None
            if detail is not None and detail.image_sources:
                ocr_stats["postings_with_images"] += 1
                if ocr_enabled:
                    resolved_image_urls = self._resolve_image_sources(
                        row,
                        detail.image_sources,
                    )
                    image_count = min(
                        len(resolved_image_urls), self.config.max_images_per_posting
                    )
                    ocr_stats["images_seen"] += image_count
                    if ocr_engine is None and not ocr_unavailable:
                        try:
                            ocr_engine = PaddleOcrEngine(
                                device=self.config.ocr_device,
                                language="korean",
                                min_confidence=self.config.ocr_min_confidence,
                            )
                            ocr_stats["engine_loaded"] = 1
                        except OcrUnavailableError as error:
                            ocr_unavailable = True
                            ocr_stats["engine_load_failures"] += 1
                            warnings.append(str(error))
                    if ocr_engine is not None:
                        ocr_text, ocr_metadata, ocr_errors = self._ocr_images(
                            row,
                            detail.image_sources,
                            ocr_engine,
                        )
                        ocr_records.append(ocr_metadata)
                        ocr_stats["images_processed"] += ocr_metadata[
                            "images_processed"
                        ]
                        ocr_stats["images_failed"] += ocr_metadata["images_failed"]
                        if ocr_metadata["status"] == "COMPLETED":
                            ocr_stats["postings_completed"] += 1
                        elif ocr_metadata["status"] == "PARTIAL":
                            ocr_stats["postings_partial"] += 1
                        else:
                            ocr_stats["postings_failed"] += 1
                        warnings.extend(
                            f"ocr {row.posting_id}: {error}" for error in ocr_errors
                        )
                        if ocr_text:
                            ocr_block = f"[OCR 이미지]\n{ocr_text}"
                            description_text = (
                                f"{description_text}\n{ocr_block}"
                                if description_text
                                else ocr_block
                            )
                    elif ocr_unavailable:
                        ocr_stats["postings_unavailable"] += 1
                        ocr_records.append(
                            {
                                "posting_id": row.posting_id,
                                "status": "UNAVAILABLE",
                                "image_count": image_count,
                                "image_urls": resolved_image_urls[:image_count],
                            }
                        )
                else:
                    resolved_image_urls = self._resolve_image_sources(
                        row,
                        detail.image_sources,
                    )[: self.config.max_images_per_posting]
                    ocr_records.append(
                        {
                            "posting_id": row.posting_id,
                            "status": "DISABLED",
                            "image_count": len(resolved_image_urls),
                            "image_urls": resolved_image_urls,
                        }
                    )
            elif detail is not None and body_status is BodyStatus.IMAGE_ONLY:
                ocr_stats["image_only_without_source"] += 1
                warnings.append(
                    f"ocr {row.posting_id}: image-only body had no discoverable "
                    "image URL"
                )

            if detail_error:
                stats["detail_failures"] += 1
                detail_failures.append(
                    {
                        "posting_id": row.posting_id,
                        "status": body_status.value,
                        "error": detail_error,
                    }
                )
                warnings.append(
                    f"detail {row.posting_id}: {body_status.value} ({detail_error})"
                )

            detail_deadline_label = detail.deadline_label if detail else None
            deadline_label = detail_deadline_label or row.deadline_label
            deadline = parse_deadline(
                deadline_label,
                default_year=self.config.start_date.year,
            )
            image_sources = (
                tuple(self._resolve_image_sources(row, detail.image_sources))
                if detail is not None
                else ()
            )
            try:
                record = normalize_jobkorea_posting(
                    item=row,
                    detail=detail,
                    description_text=description_text,
                    image_sources=image_sources,
                    posted_at=posted_at,
                    deadline=deadline,
                    collected_at=collected_at,
                    detail_fetched=self.config.fetch_details,
                    detail_error=detail_error,
                )
            except ValidationError as error:
                invalid_records.append(
                    {
                        "posting_id": row.posting_id,
                        "error": str(error.errors(include_url=False))[:800],
                    }
                )
                continue
            technology_mention_count += len(record.technology_mentions)
            records.append(record)
            # Appended only after the record validated against the contract.
            # A posting that failed validation is not claimed as collected, so
            # the next run tries it again.
            cursor.collected_ids.append(row.posting_id)
            body_status_counts[record.body_status.value] += 1
            posting_status_counts[record.posting_status.value] += 1

        _notify_progress(
            progress_callback,
            {
                "stage": "complete",
                "current": 1,
                "total": 1,
                "message": f"수집 완료: {len(records)}건",
            },
        )

        pipeline_run_id = pipeline_run_id_for(SOURCE_SITE, collected_at)
        batch = JobAnalysisInputBatch(
            schema_version=JOB_ANALYSIS_INPUT_SCHEMA_VERSION,
            dataset_snapshot_id=dataset_snapshot_id_for(
                SOURCE_SITE,
                self.config.start_date,
                self.config.end_date,
            ),
            pipeline_run_id=pipeline_run_id,
            collector_version=self.config.collector_version,
            records=tuple(records),
        )
        manifest: dict[str, Any] = {
            "source_site": SOURCE_SITE,
            "collector_version": self.config.collector_version,
            "schema_version": JOB_ANALYSIS_INPUT_SCHEMA_VERSION,
            "pipeline_run_id": pipeline_run_id,
            "dataset_snapshot_id": batch.dataset_snapshot_id,
            "collected_at": collected_at.isoformat(),
            "source": {
                "site": "JOBKOREA",
                "mode": (
                    CollectionMode.ACTIVE_LISTING.value
                    if self.config.duty_scopes
                    else "category"
                ),
                "duty_name": self.config.duty_name,
                "duty_code": self.config.duty_code,
                "list_url": self.list_url,
                "list_request": "POST /Recruit/Home/_GI_List/ (order=2, pagesize=40)",
                "detail_url_template": self.detail_url("{posting_id}"),
                # Only a scoped run carries this block. `active_snapshot_metadata`
                # hashes the codes and roles into the snapshot's `scope_key` and
                # reads each scope's own stop reason, so the per-scope outcome has
                # to survive into the manifest rather than being collapsed into
                # the run-level reason.
                **(
                    {"duty_scopes": scope_reasons}
                    if self.config.duty_scopes
                    else {}
                ),
            },
            "requested_range": {
                "start_date": self.config.start_date.isoformat(),
                "end_date": self.config.end_date.isoformat(),
                "inclusive": True,
                "timezone": "Asia/Seoul",
            },
            # Recorded in every run's manifest, not only in a doc: a batch that
            # outlives this repository still says on what basis it was
            # collected (S15P21E102-196, same block 커리어·게임잡 carry).
            #
            # This is the strongest FAIL of the three. The other two rest on a
            # terms clause and on a same-legal-entity inference; this one rests
            # on a decided case against this site's operator, for this exact
            # activity.
            "source_admission": {
                "criterion_a": "FAIL",
                "operator": "(주)잡코리아 110-81-34859",
                "basis": (
                    "-94 §3.1 — 서울고등법원이 잡코리아 공고 무단 크롤링을 "
                    "데이터베이스제작자 권리 침해로 판단(4.5억 인정, 120억 합의). "
                    "공식 API 는 신입공채·공공기관/학교로 범위가 제한되어 "
                    "직무별 기술 수요 집계에 사용할 수 없다 (§3.2)."
                ),
                "prior_decision": (
                    "-94 §1 이 제외를 결론했고 §7-2 가 코드 폐기를 지시했다. "
                    "-195 가 그 폐기를 준비했으나 머지되지 않았다."
                ),
                "admitted_by": "project owner decision, 2026-09-10",
                "note": (
                    "판례 근거는 그대로 유효하고 없어지지 않았다. 수집을 켠 것은 "
                    "근거가 바뀌었기 때문이 아니라 소유자가 위험을 감수하기로 "
                    "했기 때문이다. 로그인·CAPTCHA 우회·접근제어 우회는 하지 "
                    "않으며 요청 간격은 2초다."
                ),
            },
            "collection": {
                "collected_at": collected_at.isoformat(),
                "collector_version": self.config.collector_version,
                "pipeline_run_id": pipeline_run_id,
                "fetch_details": self.config.fetch_details,
                "ocr_images": self.config.ocr_images,
                "ocr_device": self.config.ocr_device,
                "ocr_min_confidence": self.config.ocr_min_confidence,
                "max_images_per_posting": self.config.max_images_per_posting,
            },
            "stats": {
                "pages_scanned": int(stats["pages_scanned"]),
                "raw_rows_seen": int(stats["raw_rows_seen"]),
                "unique_rows_seen": int(stats["unique_rows_seen"]),
                "duplicates_skipped": int(stats["duplicates_skipped"]),
                # The subset of `duplicates_skipped` that is one posting listed
                # under more than one duty scope, which is expected in a scoped
                # run rather than a sign of a re-read page. The 2026-09-15 run's
                # 9,128 raw rows over 5,859 distinct postings is this number.
                "cross_scope_duplicates": int(stats["cross_scope_duplicates"]),
                # In range but already written by an earlier round. Distinct
                # from `duplicates_skipped`, which is the same posting twice
                # inside one round's listing.
                "skipped_already_collected": int(stats["skipped_already_collected"]),
                "matched_rows": len(selected),
                "records_written": len(records),
                "detail_requests": int(stats["detail_requests"]),
                "detail_failures": int(stats["detail_failures"]),
                "technology_mentions": technology_mention_count,
                "scan_stop_reason": scan_stop_reason,
            },
            "counts": {
                "records": len(records),
                "pages_read": int(stats["pages_scanned"]),
                "detail_errors": len(detail_failures),
                "invalid_records": len(invalid_records),
            },
            "ocr": {
                "enabled": ocr_enabled,
                "backend": "PaddleOCR",
                "language": "korean",
                "device": self.config.ocr_device,
                "min_confidence": self.config.ocr_min_confidence,
                "stats": dict(sorted(ocr_stats.items())),
                "postings": ocr_records,
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
            "posting_status_counts": dict(sorted(posting_status_counts.items())),
            "detail_failures": detail_failures,
            "invalid_record_samples": invalid_records[:20],
            "warnings": warnings,
            "outputs": {},
            "stopped_reason": (
                "max_pages reached before date boundary"
                if scan_stop_reason == "max_pages"
                else None
            ),
            "resume": {
                "cursor_path": (
                    str(self.config.cursor_path) if self.config.cursor_path else None
                ),
                "known_ids_before": len(already),
                "known_ids_after": len(cursor.collected_ids),
            },
        }
        cursor.last_page = stats["pages_scanned"]
        return CrawlResult(
            batch=batch,
            manifest=manifest,
            cursor=cursor,
            cursor_path=self.config.cursor_path,
        )


def _notify_progress(
    callback: ProgressCallback | None,
    event: dict[str, Any],
) -> None:
    if callback is not None:
        callback(event)


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
]


def write_outputs(result: CrawlResult, output_dir: Path) -> dict[str, Path]:
    """Write validated JSON, analyst-friendly CSV, and a run manifest atomically."""

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
    # Last, and only here. The cursor asserts these postings are collected, so
    # it must not be written before the batch and the manifest are on disk —
    # a cursor saved ahead of them makes the next run skip postings whose
    # output never existed (S15P21E102-174).
    if result.cursor is not None:
        result.cursor.save(result.cursor_path)
    return {
        "json": json_path,
        "csv": csv_path,
        "manifest": manifest_path,
    }


def _atomic_write(path: Path, content: str) -> None:
    temporary_path = path.with_name(path.name + ".tmp")
    with temporary_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)
    os.replace(temporary_path, path)


def _parse_cli_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "날짜는 YYYY-MM-DD 형식이어야 합니다"
        ) from error


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="잡코리아 백엔드개발자 공고를 기간별로 CSV/JSON 수집합니다."
    )
    # Defaults are today, not the August window this collector was written
    # for. A scheduled run means "what was registered today"; a fixed range
    # would re-collect the same window on every round (S15P21E102-196).
    today = datetime.now(tz=SEOUL).date()
    parser.add_argument("--start-date", type=_parse_cli_date, default=today)
    parser.add_argument("--end-date", type=_parse_cli_date, default=today)
    parser.add_argument(
        "--days-back",
        type=int,
        default=0,
        help="widen the range to N days before --end-date (for scheduled runs)",
    )
    parser.add_argument(
        "--no-upload-raw",
        action="store_true",
        help="WEBHDFS_URL이 설정되어도 HDFS Raw 업로드를 생략합니다",
    )
    parser.add_argument(
        "--no-publish-analysis-input",
        action="store_true",
        help=(
            "Raw 업로드·검증까지만 하고 analysis_input 게시는 생략합니다. "
            "회차를 먼저 검토한 뒤 승인해 게시하려는 경우에 씁니다 — 게시는 "
            "`python -m job.collector.backfill_cli --source jobkorea --execute` "
            "로 crawl 없이 따로 수행합니다. Raw 까지 건너뛰려면 "
            "--no-upload-raw 를 쓰십시오."
        ),
    )
    parser.add_argument(
        "--cursor",
        default=None,
        help="resume-state file; omit to collect without resume support",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/jobkorea"))
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--request-delay", type=float, default=2.0)
    parser.add_argument("--detail-delay", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--duty-code", default=DEFAULT_DUTY_CODE)
    parser.add_argument(
        "--duty-preset",
        default=None,
        help=(
            "고정 duty scope 묶음으로 전체 활성 공고를 수집합니다 "
            "(예: service-roles). 지정하면 --duty-code 대신 preset 이 쓰이고 "
            "회차는 active_listing(v3) 이 됩니다."
        ),
    )
    parser.add_argument(
        "--no-detail", action="store_true", help="상세 본문 요청을 생략합니다"
    )
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        help="이미지 공고에 OCR을 적용하지 않습니다",
    )
    parser.add_argument(
        "--ocr-device",
        default="cpu",
        help="PaddleOCR 실행 장치입니다 (예: cpu, gpu:0)",
    )
    parser.add_argument(
        "--ocr-min-confidence",
        type=float,
        default=0.35,
        help="OCR 결과에 사용할 최소 신뢰도입니다 (0.0~1.0)",
    )
    parser.add_argument(
        "--max-images-per-posting",
        type=int,
        default=20,
        help="공고 하나에서 OCR할 이미지 최대 개수입니다",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> CrawlConfig:
    """Build the run configuration from parsed CLI arguments.

    Extracted from `main` so the CLI-to-config mapping is testable without a
    crawl: `--duty-preset` is the only way to start a v3 run from this
    repository, and a preset that silently produced a date-range run would be
    the reproducibility gap all over again.
    """

    if args.days_back < 0:
        raise ValueError("--days-back must not be negative")
    start_date = args.start_date
    if args.days_back:
        start_date = args.end_date - timedelta(days=args.days_back)

    duty_scopes: tuple[DutyScope, ...] = ()
    collection_mode = CollectionMode.DATE_RANGE
    duty_code = args.duty_code
    duty_name = DEFAULT_DUTY_NAME
    if args.duty_preset:
        duty_scopes = resolve_duty_preset(args.duty_preset)
        collection_mode = CollectionMode.ACTIVE_LISTING
        # The scalar fields keep describing the run for readers of the
        # manifest; the scope list is what the scan and the contract use.
        duty_code = ",".join(scope.code for scope in duty_scopes)
        duty_name = ",".join(scope.name for scope in duty_scopes)

    return CrawlConfig(
        start_date=start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
        base_url=args.base_url,
        duty_code=duty_code,
        duty_name=duty_name,
        max_pages=args.max_pages,
        request_delay=args.request_delay,
        detail_delay=args.detail_delay,
        timeout=args.timeout,
        max_attempts=args.max_attempts,
        fetch_details=not args.no_detail,
        ocr_images=not args.no_ocr,
        ocr_device=args.ocr_device,
        ocr_min_confidence=args.ocr_min_confidence,
        max_images_per_posting=args.max_images_per_posting,
        cursor_path=Path(args.cursor) if args.cursor else None,
        collection_mode=collection_mode,
        duty_scopes=duty_scopes,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        config = config_from_args(args)
        result = JobKoreaCrawler(config).run()
        paths = write_outputs(result, config.output_dir)
    except (ValueError, JobKoreaHttpError) as error:
        print(f"수집 실패: {error}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "records": len(result.batch.records),
                "pipeline_run_id": result.batch.pipeline_run_id,
                "outputs": {key: str(path) for key, path in paths.items()},
                "warnings": result.manifest["warnings"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if not args.no_upload_raw:
        sink = sink_from_env()
        if sink is None:
            print("raw=skipped (WEBHDFS_URL 미설정)", file=sys.stderr)
        else:
            run_dir = paths["manifest"].parent
            upload = sink.upload_run(
                run_dir,
                source=SOURCE_SITE,
                collected_at=(
                    result.batch.records[0].collected_at
                    if result.batch.records
                    else datetime.now(UTC)
                ),
                pipeline_run_id=result.batch.pipeline_run_id,
            )
            write_upload_record(run_dir, upload)
            if not upload.ok:
                return 1
            verification = verify_run(sink.client, run_dir)
            if not verification.ok:
                print(
                    f"raw verify failed: {verification.state}",
                    file=sys.stderr,
                )
                return 1
            if args.no_publish_analysis_input:
                # Raw is uploaded and verified, so the run is durable and can
                # be reviewed before it becomes a C input. Publishing it later
                # needs no second crawl: `job.collector.backfill_cli` reads the
                # run back out of Raw and applies the same
                # `analysis_input.release_blockers` gate.
                print(
                    "analysis_input=deferred (--no-publish-analysis-input); "
                    "publish with: python -m job.collector.backfill_cli "
                    "--source jobkorea --execute",
                    file=sys.stderr,
                )
                return 0 if result.batch.records else 1
            published = publish_from_env(
                run_dir,
                source=SOURCE_SITE,
                pipeline_run_id=result.batch.pipeline_run_id,
            )
            if published is not None and not published.ok and not published.skipped:
                return 1

    return 0 if result.batch.records else 1
