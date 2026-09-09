"""JobKorea backend-posting crawler and A-to-C batch writer."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin

from job.contracts import (
    JOB_ANALYSIS_INPUT_SCHEMA_VERSION,
    BodyStatus,
    JobAnalysisInputBatch,
    JobPostingInput,
    PostingStatus,
)

from .client import (
    JobKoreaBlockedError,
    JobKoreaHttpClient,
    JobKoreaHttpError,
)
from .dates import SEOUL, as_seoul, date_range_bounds, parse_deadline, parse_posted_at
from .ocr import (
    OcrRecognitionError,
    OcrUnavailableError,
    PaddleOcrEngine,
    image_suffix,
)
from .parser import DetailContent, JobListItem, parse_detail, parse_job_list
from .technology import extract_technology_mentions

COLLECTOR_VERSION = "jobkorea-crawler/v2"
DEFAULT_BASE_URL = "https://www.jobkorea.co.kr"
DEFAULT_DUTY_CODE = "1000229"
DEFAULT_DUTY_NAME = "백엔드개발자"
_SAFE_RUN_ID_RE = re.compile(r"[^A-Za-z0-9_.+-]+")
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

    def _list_request_data(self, page: int) -> list[tuple[str, str]]:
        return [
            ("condition[menucode]", "duty"),
            ("condition[duty]", self.config.duty_code),
            ("page", str(page)),
            ("direct", "0"),
            ("order", "2"),
            ("pagesize", str(self.config.page_size)),
            ("tabindex", "0"),
            ("onePick", "0"),
            ("confirm", "0"),
            ("profile", "0"),
        ]

    def _fetch_list_page(self, page: int) -> list[JobListItem]:
        html = self.client.post(
            "/Recruit/Home/_GI_List/",
            self._list_request_data(page),
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
        selected: list[tuple[JobListItem, datetime]] = []
        stats: Counter[str] = Counter()
        stopped_reason = "max_pages"
        cursor = Cursor.load(self.config.cursor_path, self.config)
        already = set(cursor.collected_ids)

        for page in range(1, self.config.max_pages + 1):
            _notify_progress(
                progress_callback,
                {
                    "stage": "list",
                    "current": page,
                    "total": self.config.max_pages,
                    "message": f"목록 페이지 {page} 수집 중",
                },
            )
            rows = self._fetch_list_page(page)
            stats["pages_scanned"] += 1
            stats["raw_rows_seen"] += len(rows)
            if not rows:
                if page == 1:
                    raise JobKoreaHttpError(
                        "JobKorea list response contained no parseable postings"
                    )
                stopped_reason = "empty_page"
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
                    continue
                seen_ids.add(row.posting_id)
                stats["unique_rows_seen"] += 1
                if posted_at is not None and start_at <= posted_at < end_exclusive:
                    # Skipped before the detail request, which is the point:
                    # a resumed run must not re-fetch a posting it already
                    # wrote. The date shortcut below still reads every page's
                    # labels, so skipping here cannot end the scan early.
                    if row.posting_id in already:
                        stats["skipped_already_collected"] += 1
                        continue
                    selected.append((row, posted_at))

            if unknown_date_count:
                warnings.append(
                    f"page {page}: {unknown_date_count} row(s) had an "
                    "unparsed registration label"
                )

            # The POST request is explicitly sorted by registration date. Once a
            # complete page is older than the requested range, later pages are
            # outside the range as well. Unknown labels disable this shortcut.
            if (
                len(page_dates) == len(rows)
                and page_dates
                and max(page_dates) < start_at
            ):
                stopped_reason = "before_start_date"
                break
            if len(rows) < self.config.page_size:
                stopped_reason = "short_page"
                break
        else:
            warnings.append("max_pages reached before the date boundary was observed")

        if not self.config.fetch_details:
            warnings.append(
                "detail fetching disabled; records have body_status=MISSING"
            )
        ocr_enabled = self.config.fetch_details and self.config.ocr_images
        if self.config.ocr_images and not self.config.fetch_details:
            warnings.append("OCR skipped because detail fetching is disabled")

        records: list[JobPostingInput] = []
        detail_failures: list[dict[str, str]] = []
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
            posting_status = _posting_status(
                deadline_label,
                deadline,
                collected_at,
            )
            raw_artifact_uri = (
                self.detail_url(row.posting_id)
                if body_status is BodyStatus.IMAGE_ONLY
                else None
            )
            technology_mentions = extract_technology_mentions(
                row.title,
                description_text,
            )
            technology_mention_count += len(technology_mentions)
            content_basis = "\n".join(
                [
                    row.posting_id,
                    row.company_name,
                    row.title,
                    description_text or "",
                    deadline_label or "",
                ]
            )
            record = JobPostingInput(
                source_record_id=f"jobkorea:{row.posting_id}",
                canonical_job_id=None,
                source_site="JOBKOREA",
                source_posting_id=row.posting_id,
                source_url=row.source_url,
                company_name=row.company_name or "(회사명 미확인)",
                title=row.title,
                raw_job_category=self.config.duty_name,
                career_level=row.career_level,
                region=row.region,
                description_text=description_text,
                raw_artifact_uri=raw_artifact_uri,
                body_status=body_status,
                posting_status=posting_status,
                posted_at=posted_at,
                deadline=deadline,
                collected_at=collected_at,
                content_hash=sha256(content_basis.encode("utf-8")).hexdigest(),
                technology_mentions=technology_mentions,
            )
            records.append(record)
            # Appended only after the record validated against the contract.
            # A posting that failed validation is not claimed as collected, so
            # the next run tries it again.
            cursor.collected_ids.append(row.posting_id)
            body_status_counts[body_status.value] += 1
            posting_status_counts[posting_status.value] += 1

        _notify_progress(
            progress_callback,
            {
                "stage": "complete",
                "current": 1,
                "total": 1,
                "message": f"수집 완료: {len(records)}건",
            },
        )

        pipeline_run_id = _pipeline_run_id(collected_at)
        batch = JobAnalysisInputBatch(
            schema_version=JOB_ANALYSIS_INPUT_SCHEMA_VERSION,
            dataset_snapshot_id=(
                f"jobkorea-{self.config.start_date.isoformat()}"
                f"_{self.config.end_date.isoformat()}"
            ),
            pipeline_run_id=pipeline_run_id,
            collector_version=COLLECTOR_VERSION,
            records=tuple(records),
        )
        manifest: dict[str, Any] = {
            "source": {
                "site": "JOBKOREA",
                "mode": "category",
                "duty_name": self.config.duty_name,
                "duty_code": self.config.duty_code,
                "list_url": self.list_url,
                "list_request": "POST /Recruit/Home/_GI_List/ (order=2, pagesize=40)",
                "detail_url_template": self.detail_url("{posting_id}"),
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
                "collector_version": COLLECTOR_VERSION,
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
                # In range but already written by an earlier round. Distinct
                # from `duplicates_skipped`, which is the same posting twice
                # inside one round's listing.
                "skipped_already_collected": int(stats["skipped_already_collected"]),
                "matched_rows": len(selected),
                "records_written": len(records),
                "detail_requests": int(stats["detail_requests"]),
                "detail_failures": int(stats["detail_failures"]),
                "technology_mentions": technology_mention_count,
                "stopped_reason": stopped_reason,
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
            "warnings": warnings,
            "outputs": {},
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


def _pipeline_run_id(collected_at: datetime) -> str:
    raw = f"jobkorea-{collected_at.strftime('%Y%m%dT%H%M%S%z')}"
    return _SAFE_RUN_ID_RE.sub("-", raw)


def _posting_status(
    deadline_label: str | None,
    deadline: datetime | None,
    collected_at: datetime,
) -> PostingStatus:
    normalized = (deadline_label or "").replace(" ", "")
    if "상시채용" in normalized or "채용시마감" in normalized:
        return PostingStatus.ACTIVE
    if deadline is None:
        return PostingStatus.UNKNOWN
    return PostingStatus.CLOSED if deadline < collected_at else PostingStatus.ACTIVE


CSV_FIELDS = [
    "source_record_id",
    "canonical_job_id",
    "source_site",
    "source_posting_id",
    "source_url",
    "company_name",
    "title",
    "raw_job_category",
    "career_level",
    "region",
    "description_text",
    "raw_artifact_uri",
    "body_status",
    "posting_status",
    "posted_at",
    "deadline",
    "collected_at",
    "content_hash",
    "technology_mentions",
]


def write_outputs(result: CrawlResult, output_dir: Path) -> dict[str, Path]:
    """Write validated JSON, analyst-friendly CSV, and a run manifest atomically."""

    run_dir = output_dir / result.batch.pipeline_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    json_path = run_dir / "job_analysis_input_v1.json"
    csv_path = run_dir / "jobs.csv"
    manifest_path = run_dir / "manifest.json"

    batch_payload = result.batch.model_dump(mode="json", by_alias=True)
    batch_text = json.dumps(batch_payload, ensure_ascii=False, indent=2) + "\n"
    _atomic_write(json_path, batch_text)

    with csv_path.with_suffix(".csv.tmp").open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for record in result.batch.records:
            row = record.model_dump(mode="json", by_alias=True)
            row["technology_mentions"] = json.dumps(
                row["technology_mentions"],
                ensure_ascii=False,
            )
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})
    csv_path.with_suffix(".csv.tmp").replace(csv_path)

    manifest = dict(result.manifest)
    # Match this writer's existing Path.write_text newline translation exactly.
    batch_bytes = batch_text.replace("\n", os.linesep).encode("utf-8")
    manifest["output_sha256"] = {json_path.name: sha256(batch_bytes).hexdigest()}
    manifest["outputs"] = {
        "job_analysis_input_v1.json": json_path.name,
        "jobs.csv": csv_path.name,
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
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(content, encoding="utf-8")
    temporary_path.replace(path)


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


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        if args.days_back < 0:
            raise ValueError("--days-back must not be negative")
        start_date = args.start_date
        if args.days_back:
            start_date = args.end_date - timedelta(days=args.days_back)
        config = CrawlConfig(
            start_date=start_date,
            end_date=args.end_date,
            output_dir=args.output_dir,
            base_url=args.base_url,
            duty_code=args.duty_code,
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
        )
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
    return 0
