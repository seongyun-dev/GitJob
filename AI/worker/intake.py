"""Read-only completed-output intake with durable PostgreSQL event deduplication.

Collectors atomically publish manifest.json last. No source is moved, deleted,
or acknowledged remotely. Configured cohorts use a verified observed-input union.
"""

import hashlib
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Literal
from zoneinfo import ZoneInfo

import psycopg
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from job.cohort import (
    CohortCriteria,
    CohortPurpose,
    requires_original_posting_date,
)
from job.contracts import BodyStatus, JobAnalysisInputBatch
from job.input_union import selected_input_totals
from job.jobkorea_contract import active_snapshot_metadata
from worker.job_hdfs_source import JobHdfsSourceConfig
from worker.lease import LeaseHeartbeat
from worker.store import ComputeStore, digest

LOGGER = logging.getLogger(__name__)
INTAKE_VERSION = "c-completed-output-intake/v1"
MAX_JOB_SET_BYTES = 128 * 1024 * 1024
MAX_JOB_SET_RECORDS = 50_000
MAX_JOB_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_JOB_BATCH_BYTES = 64 * 1024 * 1024
COMMON_JOB_BATCH_FILENAME = "job_analysis_input.json"
LEGACY_JOBKOREA_BATCH_FILENAME = "job_analysis_input_v1.json"
MONTHLY_DEMAND_MONTHS = 12
JOB_TREND_RANGES = (3, 6, 12)


class PublicInputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    root_uri: str
    namenode_base_url: str
    datanode_routes: dict[str, str] = Field(default_factory=dict)
    artifact_root_uris: tuple[str, ...] = Field(default=(), max_length=4)
    checkpoint_dir: Path
    hdfs_user: str = "hadoop"
    include_partial: StrictBool = False
    max_records: int = Field(default=500, ge=1, le=10000, strict=True)
    max_declared_bytes: int = Field(
        default=50_000_000, ge=1, le=100_000_000, strict=True
    )
    max_requests: int = Field(default=8000, ge=1, le=100000, strict=True)

    @model_validator(mode="after")
    def validate_source(self):
        from github.artifact_reader import ReadOnlyWebHdfsReader

        if not self.checkpoint_dir.is_absolute():
            raise ValueError("checkpoint directory must be absolute")
        ReadOnlyWebHdfsReader(
            self.namenode_base_url,
            self.root_uri,
            additional_uri_prefixes=self.artifact_root_uris,
            datanode_routes=self.datanode_routes,
            user=self.hdfs_user,
            max_requests=self.max_requests,
        )
        return self


class IntakeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["c-intake-config/v1"]
    job_roots: tuple[Path, ...] = Field(default=(), max_length=32)
    criteria: tuple[CohortCriteria, ...] = Field(default=(), max_length=32)
    # One entry is one immutable publication, and each holds its own loaded
    # snapshot and checkpoint, so the bound exists to keep a poll cycle's cost
    # predictable rather than to cap how many pipelines may publish. Four was
    # exactly the number of Historical months in flight, which left no room for
    # the Weekly publication: a fifth entry failed validation and took the
    # whole worker down with it, Historical polling included (S15P21E102-286).
    public_sources: tuple[PublicInputConfig, ...] = Field(default=(), max_length=8)
    # Published job runs on HDFS (S15P21E102-220). Staged to local directories
    # before each poll and then read by the same loader as `job_roots`; see
    # `worker.job_hdfs_source`. Configuring these is an alternative to naming
    # local roots by hand, not a different way of judging the inputs.
    job_hdfs_sources: tuple[JobHdfsSourceConfig, ...] = Field(default=(), max_length=4)
    poll_seconds: int = Field(default=30, ge=1, le=3600, strict=True)
    max_manifests: int = Field(default=1000, ge=1, le=10000, strict=True)

    @model_validator(mode="after")
    def configured_sources(self):
        if not self.job_roots and not self.public_sources and not self.job_hdfs_sources:
            raise ValueError("at least one completed input source is required")
        if bool(self.job_roots or self.job_hdfs_sources) != bool(self.criteria):
            raise ValueError(
                "job inputs and cohort criteria must be configured together"
            )
        for root in self.job_roots:
            if (
                not root.is_absolute()
                or not root.is_dir()
                or root.is_symlink()
                or root.is_junction()
            ):
                raise ValueError("input roots must be existing absolute directories")
        if len({p.resolve() for p in self.job_roots}) != len(self.job_roots):
            raise ValueError("duplicate input roots")
        if len({p.checkpoint_dir.resolve() for p in self.public_sources}) != len(
            self.public_sources
        ):
            raise ValueError("each public source requires its own checkpoint directory")
        if len({s.staging_dir.resolve() for s in self.job_hdfs_sources}) != len(
            self.job_hdfs_sources
        ):
            raise ValueError("each job HDFS source requires its own staging directory")
        return self


@dataclass(frozen=True)
class JobOutput:
    batch: JobAnalysisInputBatch
    occurred_at: datetime
    batch_sha256: str
    manifest_sha256: str
    collection_issues: tuple[str, ...]
    mixed_date_semantics: bool = False
    source_site: str | None = None
    batch_size_bytes: int = 0
    snapshot_mode: str | None = None
    snapshot_scope_key: str | None = None
    snapshot_complete: bool = False


def _monthly_demand_criteria(outputs, templates):
    """Build the exact completed-month scopes requested by the JOB Trend UI.

    Active matching and historical demand deliberately use different cohorts. The
    deployment config only needs the live target templates; the intake derives the
    latest twelve completed Seoul months from the verified observation cutoff.
    """

    if not outputs:
        return ()
    seoul = ZoneInfo("Asia/Seoul")
    scopes = {
        (
            template.target_role,
            template.regions,
            template.career_levels,
        )
        for template in templates
        if template.purpose is CohortPurpose.ACTIVE_MATCHING
    }
    generated = []
    for target_role, regions, career_levels in sorted(scopes):
        relevant = tuple(outputs)
        cutoff = max(output.occurred_at for output in relevant)
        current_month = cutoff.astimezone(seoul).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        last_complete = (current_month - timedelta(days=1)).replace(day=1)
        starts = []
        cursor = last_complete
        for _ in range(MONTHLY_DEMAND_MONTHS):
            starts.append(cursor)
            cursor = (cursor - timedelta(days=1)).replace(day=1)
        for start in reversed(starts):
            end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
            generated.append(
                CohortCriteria(
                    target_role=target_role,
                    purpose=CohortPurpose.MONTHLY_DEMAND,
                    as_of=cutoff,
                    posted_from=start,
                    posted_to=end,
                    sources=(),
                    regions=regions,
                    career_levels=career_levels,
                    min_jobs=1,
                )
            )
    return tuple(generated)


def _stamp(path: Path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _contained(path: Path, root: Path) -> Path:
    root = root.resolve(strict=True)
    path = path.absolute()
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise ValueError("input is outside the trusted root") from None
    current = root
    for part in relative.parts:
        if part in (".", ".."):
            raise ValueError("input path traversal")
        current /= part
        if current.is_symlink() or current.is_junction():
            raise ValueError("input links are not allowed")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("input must be a contained regular file")
    return resolved


def _read(path: Path, maximum: int) -> bytes:
    if path.stat().st_size > maximum:
        raise ValueError("input exceeds configured size limit")
    with path.open("rb") as handle:
        raw = handle.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("input exceeds configured size limit")
    return raw


def _job_batch_layout(manifest: dict[str, object]) -> tuple[str, bool]:
    """Select the fixed batch filename and whether this is legacy JobKorea.

    JobKorea V1 used a nested manifest and ``job_analysis_input_v1.json``.
    Current JobKorea runs use the same top-level manifest and filename as the
    other collectors. The declared fixed output, rather than the source name,
    distinguishes the two so historical snapshots remain readable.
    """

    outputs = manifest.get("outputs")
    source = manifest.get("source")
    is_jobkorea = isinstance(source, dict) and source.get("site") == "JOBKOREA"
    is_legacy = (
        is_jobkorea
        and isinstance(outputs, dict)
        and outputs.get(LEGACY_JOBKOREA_BATCH_FILENAME)
        == LEGACY_JOBKOREA_BATCH_FILENAME
        and outputs.get(COMMON_JOB_BATCH_FILENAME) != COMMON_JOB_BATCH_FILENAME
    )
    return (
        LEGACY_JOBKOREA_BATCH_FILENAME if is_legacy else COMMON_JOB_BATCH_FILENAME,
        is_legacy,
    )


def _jobkorea_v3_snapshot_metadata(
    manifest: dict[str, object], batch: JobAnalysisInputBatch
) -> tuple[str | None, str | None, bool, bool]:
    """Return active-snapshot scope and record-local detail reconciliation.

    Only the JobKorea v3 full active collector has this contract.  Older and
    date-bounded producers keep the existing fail-closed detail-error gate.
    """

    snapshot = active_snapshot_metadata(manifest)
    if snapshot is None:
        return None, None, False, False
    counts = manifest.get("counts")
    detail_errors = counts.get("detail_errors", 0) if isinstance(counts, dict) else 0
    blocked = sum(record.body_status is BodyStatus.BLOCKED for record in batch.records)
    reconciled = (
        type(detail_errors) is int and detail_errors > 0 and detail_errors == blocked
    )
    return "active_listing", snapshot.scope_key, snapshot.complete, reconciled


def load_job_output(manifest_path: Path, root: Path) -> JobOutput:
    manifest_path = _contained(manifest_path, root)
    if manifest_path.name != "manifest.json":
        raise ValueError("only the producer completion manifest is accepted")
    manifest_before = _stamp(manifest_path)
    manifest_raw = _read(manifest_path, MAX_JOB_MANIFEST_BYTES)
    manifest = json.loads(manifest_raw)
    if not isinstance(manifest, dict):
        raise TypeError("manifest must be an object")
    for field in (
        "outputs",
        "output_sha256",
        "source",
        "collection",
        "counts",
        "stats",
        "listing_date_labels",
    ):
        if field in manifest and not isinstance(manifest[field], dict):
            raise ValueError("manifest nested metadata must be objects")
    batch_name, legacy_jobkorea = _job_batch_layout(manifest)
    batch_path = _contained(manifest_path.parent / batch_name, root)
    before = manifest_before, _stamp(batch_path)
    batch_raw = _read(batch_path, MAX_JOB_BATCH_BYTES)
    batch = JobAnalysisInputBatch.model_validate_json(batch_raw)
    if manifest.get("outputs", {}).get(batch_name) != batch_name:
        raise ValueError("manifest output must name the fixed sibling batch")
    if (
        before != (_stamp(manifest_path), _stamp(batch_path))
        or _read(manifest_path, MAX_JOB_MANIFEST_BYTES) != manifest_raw
    ):
        raise ValueError("producer output changed while being read")
    issues = []
    declared_hashes = manifest.get("output_sha256")
    if declared_hashes is None:
        issues.append("UNBOUND_LEGACY_MANIFEST")
    elif (
        not isinstance(declared_hashes, dict)
        or declared_hashes.get(batch_name) != hashlib.sha256(batch_raw).hexdigest()
    ):
        raise ValueError("completion manifest does not bind the current batch bytes")
    if legacy_jobkorea:
        metadata = manifest["collection"]
        count = manifest["stats"]["records_written"]
        source = "JOBKOREA"
        stopped = manifest["stats"].get("stopped_reason")
        if stopped not in ("empty_page", "before_start_date", "short_page"):
            issues.append("COLLECTOR_STOPPED_EARLY")
        if manifest["stats"].get("detail_failures", 0):
            issues.append("DETAIL_COLLECTION_FAILED")
    else:
        metadata = manifest
        count = manifest["counts"]["records"]
        source = manifest.get("source_site")
        if (
            manifest.get("schema_version") != batch.schema_version
            or manifest.get("dataset_snapshot_id") != batch.dataset_snapshot_id
        ):
            raise ValueError("manifest dataset/schema does not match the batch")
        if manifest.get("stopped_reason"):
            issues.append("COLLECTOR_STOPPED_EARLY")
        snapshot_mode, snapshot_scope_key, snapshot_complete, detail_reconciled = (
            _jobkorea_v3_snapshot_metadata(manifest, batch)
        )
        if snapshot_mode and not snapshot_complete:
            issues.append("COLLECTOR_STOPPED_EARLY")
        if manifest["counts"].get("detail_errors", 0) and not detail_reconciled:
            issues.append("DETAIL_COLLECTION_FAILED")
        if manifest["counts"].get("invalid_records", 0):
            issues.append("INVALID_SOURCE_RECORDS")
    if legacy_jobkorea:
        snapshot_mode = snapshot_scope_key = None
        snapshot_complete = False
    for key in ("collector_version", "pipeline_run_id"):
        if metadata.get(key) != getattr(batch, key):
            raise ValueError("manifest identity does not match the batch")
    occurred_at = datetime.fromisoformat(metadata["collected_at"])
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("manifest timestamp requires a timezone")
    if type(count) is not int or count != len(batch.records):
        raise ValueError("manifest record count does not match the batch")
    # CAREER · GAMEJOB were missing here, and not on purpose — this list
    # predates both collectors and nobody added them, so the 커리어 회차
    # (2026-09-09, 1,139건) could not be read at all. S15P21E102-196 admitted
    # all three 기준 A 미통과 source 로, which settles it: the reader accepts
    # every site the scheduler is allowed to run.
    if source not in ("SARAMIN", "WORKNET", "JOBKOREA", "CAREER", "GAMEJOB") or any(
        r.source_site != source or r.collected_at != occurred_at for r in batch.records
    ):
        raise ValueError("manifest source/timestamp does not match the records")
    return JobOutput(
        batch,
        occurred_at,
        hashlib.sha256(batch_raw).hexdigest(),
        hashlib.sha256(manifest_raw).hexdigest(),
        tuple(sorted(set(issues))),
        bool(manifest.get("listing_date_labels", {}).get("수정일", 0)),
        source,
        len(batch_raw),
        snapshot_mode,
        snapshot_scope_key,
        snapshot_complete,
    )


def publish_job_output(
    loaded: JobOutput, criteria: CohortCriteria, *, store, mapper, registry
):
    from worker.api import compute_versions
    from worker.jobs import job_artifacts

    if loaded.collection_issues:
        raise ValueError("incomplete collection requires quality-aware review")
    if loaded.mixed_date_semantics and requires_original_posting_date(criteria):
        raise ValueError("modified dates cannot be treated as original posting dates")
    request = {
        "intake_version": INTAKE_VERSION,
        "dataset_snapshot_id": loaded.batch.dataset_snapshot_id,
        "batch_sha256": loaded.batch_sha256,
        "manifest_sha256": loaded.manifest_sha256,
        "criteria": criteria.model_dump(mode="json"),
        "compute_versions": compute_versions("JOB_BATCH", registry),
    }
    ticket = store.claim(
        event_id="job-intake-" + digest(request),
        kind="JOB_BATCH",
        owner=None,
        occurred_at=loaded.occurred_at,
        request=request,
    )
    if ticket.status == "COMPLETED":
        return {"status": "COMPLETED", "results": ticket.results}
    if ticket.token is None:
        return {"status": "PREPARING", "results": []}
    try:
        with LeaseHeartbeat(store, ticket):
            results = store.complete(
                ticket,
                job_artifacts(
                    loaded.batch, criteria, mapper, request["compute_versions"]
                ),
            )
    except Exception:
        try:
            store.fail(ticket, "INTAKE_COMPUTE_FAILED")
        except psycopg.Error:
            LOGGER.warning(
                "C intake failure recording unavailable; lease recovery required"
            )
        raise
    return {"status": "COMPLETED", "results": results}


def publish_job_input_set(outputs, criteria, *, store, mapper, registry):
    from collections import defaultdict

    from job.demand import aggregate_demand
    from job.input_union import build_input_union
    from worker.api import compute_versions
    from worker.jobs import job_review_records
    from worker.store import Artifact

    cohort = build_input_union(tuple(outputs), criteria, mapper)
    versions = compute_versions("JOB_BATCH", registry)
    request = {"input_union_cohort_id": cohort.cohort_id, "compute_versions": versions}
    identity = digest(request)
    ticket = store.claim(
        event_id="job-union-" + identity,
        kind="JOB_BATCH",
        owner=None,
        occurred_at=criteria.as_of,
        request=request,
    )
    if ticket.status == "COMPLETED":
        return {"status": "COMPLETED", "results": ticket.results}
    if ticket.token is None:
        return {"status": "PREPARING", "results": []}
    try:
        with LeaseHeartbeat(store, ticket):
            output_by_source = {
                (
                    output.batch.dataset_snapshot_id,
                    output.batch_sha256,
                    output.manifest_sha256,
                ): output
                for output in outputs
            }
            selected_indexes = defaultdict(list)
            for observation in cohort.input_union.observations:
                if observation.disposition in {"SELECTED", "CONFLICT"}:
                    selected_indexes[observation.input_id].append(
                        observation.record_index
                    )
            review_records = []
            for source in cohort.input_union.input_batches:
                output = output_by_source[
                    (
                        source.dataset_snapshot_id,
                        source.batch_sha256,
                        source.manifest_sha256,
                    )
                ]
                selected_batch = output.batch.model_copy(
                    update={
                        "records": tuple(
                            output.batch.records[index]
                            for index in selected_indexes[source.input_id]
                        )
                    }
                )
                review_records.extend(job_review_records(selected_batch, mapper))
            results = store.complete(
                ticket,
                [
                    Artifact(
                        "COHORT",
                        None,
                        cohort.model_dump(mode="json"),
                        identity,
                        review_records=tuple(review_records),
                    ),
                    Artifact(
                        "DEMAND",
                        None,
                        aggregate_demand(cohort).model_dump(mode="json"),
                        identity,
                    ),
                ],
            )
    except Exception:
        try:
            store.fail(ticket, "INPUT_UNION_COMPUTE_FAILED")
        except psycopg.Error:
            LOGGER.warning("C input union requires lease recovery")
        raise
    return {"status": "COMPLETED", "results": results}


def _publish_job_trend_range(demand_refs, periods, *, store, registry):
    """Persist every Registry technology for one exact UI period selector."""

    from trend.job import job_trend
    from worker.api import compute_versions
    from worker.store import Artifact
    from worker.trend_streams import source_trend_stream

    versions = compute_versions("TREND", registry)
    request = {
        "source": "JOB",
        "periods": periods,
        "demand_snapshot_ids": tuple(snapshot_id for snapshot_id, _ in demand_refs),
        "compute_versions": versions,
    }
    ticket = store.claim(
        event_id="job-trend-intake-" + digest(request),
        kind="TREND",
        owner=None,
        occurred_at=max(demand.criteria.as_of for _, demand in demand_refs),
        request=request,
    )
    if ticket.status == "COMPLETED":
        return True
    if ticket.token is None:
        return False
    try:
        artifacts = []
        snapshots = tuple(demand for _, demand in demand_refs)
        for technology in registry.technologies:
            if technology.status.value != "ACTIVE":
                continue
            result = job_trend(technology.tech_id, snapshots, registry, periods=periods)
            artifacts.append(
                Artifact(
                    "TREND",
                    None,
                    result.model_dump(mode="json"),
                    source_trend_stream(
                        tech_id=technology.tech_id,
                        source="JOB",
                        periods=periods,
                        versions=versions,
                        filters=result.filters,
                    ),
                )
            )
        with LeaseHeartbeat(store, ticket):
            store.complete(ticket, artifacts)
    except Exception:
        try:
            store.fail(ticket, "JOB_TREND_INTAKE_FAILED")
        except psycopg.Error:
            LOGGER.warning("C JOB Trend intake requires lease recovery")
        raise
    return True


def publish_monthly_job_trends(outputs, templates, *, store, mapper, registry):
    """Materialize the 3/6/12-month JOB Trend heads consumed by the browser."""

    from collections import defaultdict

    from job.demand import DemandSnapshot

    grouped = defaultdict(list)
    for criteria in _monthly_demand_criteria(outputs, templates):
        published = publish_job_input_set(
            outputs, criteria, store=store, mapper=mapper, registry=registry
        )
        if published["status"] != "COMPLETED":
            return {"status": "PREPARING"}
        demand_id = next(
            (
                result["snapshot_id"]
                for result in published["results"]
                if result["kind"] == "DEMAND"
            ),
            None,
        )
        stored = (
            store.get_snapshot(demand_id, owner=None)
            if isinstance(demand_id, str)
            else None
        )
        if stored is None or stored["kind"] != "DEMAND":
            raise RuntimeError("monthly demand snapshot was not persisted")
        demand = DemandSnapshot.model_validate(stored["payload"])
        scope = (
            demand.criteria.target_role,
            demand.criteria.sources,
            demand.criteria.regions,
            demand.criteria.career_levels,
            demand.criteria.min_jobs,
        )
        grouped[scope].append((demand_id, demand))

    for demands in grouped.values():
        ordered = sorted(demands, key=lambda item: item[1].criteria.complete_month())
        for count in JOB_TREND_RANGES:
            if len(ordered) < count:
                continue
            selected = tuple(ordered[-count:])
            periods = tuple(demand.criteria.complete_month() for _, demand in selected)
            if not _publish_job_trend_range(
                selected, periods, store=store, registry=registry
            ):
                return {"status": "PREPARING"}
    return {"status": "COMPLETED"}


class IntakeRunner:
    def __init__(
        self,
        config: IntakeConfig,
        *,
        job_sink: Callable,
        public_sinks: tuple[Callable, ...] = (),
        job_set_sink: Callable | None = None,
        job_trend_sink: Callable | None = None,
        job_input_guard: Callable | None = None,
        job_source_refresh: Callable | None = None,
    ):
        self.config, self.job_sink = config, job_sink
        self.public_sinks = public_sinks
        self.job_set_sink = job_set_sink
        self.job_trend_sink = job_trend_sink
        self.job_input_guard = job_input_guard
        # Staged HDFS runs join the configured local roots. Held on the
        # instance rather than the frozen config because `poll_once` refreshes
        # them; the configured roots themselves never change.
        self.job_source_refresh = job_source_refresh
        self._job_roots = tuple(config.job_roots)
        self._current_jobs = {}
        self._job_set_cache = {}
        self._verified_job_outputs = ()
        self._verified_job_signature = None
        self._job_trend_signature = None
        self._job_set_lock = RLock()
        self._known_manifests = {}
        self.public_reports = [{} for _ in public_sinks]
        self._public_completed = set()
        self._completed = set()
        self._stop = Event()
        self._thread: Thread | None = None
        self.last_report = {"completed": 0, "failed": 0, "blocked": 0, "pending": 0}

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def current_job_result(self, criteria):
        with self._job_set_lock:
            return self._current_jobs.get(digest(criteria.model_dump(mode="json")))

    def _resolve_verified_job_locked(self, criteria):
        outputs = self._verified_job_outputs
        if not outputs or self._verified_job_signature is None:
            return None, False
        relevant = tuple(
            value
            for value in outputs
            if not criteria.sources or value.source_site in criteria.sources
        )
        if not relevant or (
            any(value.mixed_date_semantics for value in relevant)
            and requires_original_posting_date(criteria)
        ):
            return None, False
        signature = digest(
            sorted({(value.batch_sha256, value.manifest_sha256) for value in relevant})
        )
        key = digest(criteria.model_dump(mode="json"))
        cached = self._job_set_cache.get(key)
        if cached and cached[0] == signature:
            return cached[1], False
        result = self.job_set_sink(relevant, criteria)
        if result["status"] == "COMPLETED":
            self._job_set_cache[key] = (signature, result)
        return result, True

    def resolve_job_criteria(self, criteria):
        """Compute one requested cohort from the latest verified immutable input set."""
        with self._job_set_lock:
            result, _ = self._resolve_verified_job_locked(criteria)
            return result

    def resolve_job_selector(self, selector):
        """Bind B's stable filters to the verified input union observation cutoff."""
        with self._job_set_lock:
            if not self._verified_job_outputs or self._verified_job_signature is None:
                return None
            criteria = self._selector_criteria(
                self._verified_job_outputs,
                target_role=selector.target_role,
                sources=selector.sources or (),
                regions=selector.regions,
                career_levels=selector.career_levels,
                min_jobs=1 if selector.min_jobs is None else selector.min_jobs,
            )
            if criteria is None:
                return None
            result, _ = self._resolve_verified_job_locked(criteria)
            return (criteria, result) if result is not None else None

    def _publish_input_set(self, outputs, report):
        signature = digest(
            sorted({(value.batch_sha256, value.manifest_sha256) for value in outputs})
        )
        with self._job_set_lock:
            self._verified_job_outputs = tuple(outputs)
            self._verified_job_signature = signature
            current = {}
            criteria_by_key = {
                digest(criteria.model_dump(mode="json")): criteria
                for criteria in self.config.criteria
            }
            criteria_by_key.update(
                {
                    digest(criteria.model_dump(mode="json")): criteria
                    for criteria in self._latest_selector_criteria(outputs)
                }
            )
            for criteria in criteria_by_key.values():
                if self._stop.is_set():
                    return
                key = digest(criteria.model_dump(mode="json"))
                try:
                    result, computed = self._resolve_verified_job_locked(criteria)
                    if result and result["status"] == "COMPLETED":
                        current[key] = result
                        report["completed"] += int(computed)
                    else:
                        report["pending"] += 1
                except (
                    ValueError,
                    OSError,
                    RuntimeError,
                    KeyError,
                    TypeError,
                    psycopg.Error,
                ) as exc:
                    report["failed"] += 1
                    LOGGER.warning(
                        "C input union failed error_type=%s", type(exc).__name__
                    )
            if self.job_trend_sink and self._job_trend_signature != signature:
                try:
                    trend = self.job_trend_sink(outputs, self.config.criteria)
                    if trend and trend["status"] == "COMPLETED":
                        self._job_trend_signature = signature
                    else:
                        report["pending"] += 1
                except (
                    ValueError,
                    OSError,
                    RuntimeError,
                    KeyError,
                    TypeError,
                    psycopg.Error,
                ) as exc:
                    report["failed"] += 1
                    LOGGER.warning(
                        "C JOB Trend intake failed error_type=%s", type(exc).__name__
                    )
            self._current_jobs = current

    def _latest_selector_criteria(self, outputs):
        """Build the live selector scopes that HTTP callers are expected to request.

        Configured criteria can retain a historical cutoff for reproducibility. B's selector,
        however, binds the same role and filters to the newest verified observation cutoff.
        Precomputing that additive scope during intake keeps the first browser request from
        paying the full cohort build cost after every Worker restart.
        """
        selectors = []
        for template in self.config.criteria:
            if template.purpose is not CohortPurpose.ACTIVE_MATCHING:
                continue
            # 설정 criteria는 월별 계산과 검증용으로 min_jobs/as_of를 고정할 수 있다.
            # BE selector는 min_jobs를 보내지 않아 1이고 sources도 생략한다. 설정에
            # source가 있으면 그 exact selector와 BE의 전체-source selector를 모두
            # 준비해야 첫 HTTP 요청이 다른 key로 다시 계산하지 않는다.
            source_scopes = (template.sources, ()) if template.sources else ((),)
            for sources in source_scopes:
                current = self._selector_criteria(
                    outputs,
                    target_role=template.target_role,
                    sources=sources,
                    regions=template.regions,
                    career_levels=template.career_levels,
                    min_jobs=1,
                )
                if current is not None:
                    selectors.append(current)
        return tuple(
            {digest(item.model_dump(mode="json")): item for item in selectors}.values()
        )

    @staticmethod
    def _selector_criteria(
        outputs,
        *,
        target_role,
        sources,
        regions,
        career_levels,
        min_jobs,
    ):
        """Use one identity rule for poll prewarm, capacity and HTTP resolution."""
        relevant = tuple(
            output for output in outputs if not sources or output.source_site in sources
        )
        if not relevant:
            return None
        return CohortCriteria(
            target_role=target_role,
            as_of=max(output.occurred_at for output in relevant),
            sources=sources,
            regions=regions,
            career_levels=career_levels,
            min_jobs=min_jobs,
        )

    def _validate_job_set_capacity(self, outputs):
        """Apply the input budget after active-snapshot selection.

        Configured historical criteria keep their full observed union. A dynamic
        selector always resolves the latest ACTIVE_MATCHING view, so validate that
        view as well even when the configured calculations use an older cutoff.
        """

        criteria = {
            digest(item.model_dump(mode="json")): item for item in self.config.criteria
        }
        for current in self._latest_selector_criteria(outputs):
            criteria.setdefault(digest(current.model_dump(mode="json")), current)
        for item in criteria.values():
            input_records, input_bytes = selected_input_totals(tuple(outputs), item)
            if input_records > MAX_JOB_SET_RECORDS or input_bytes > MAX_JOB_SET_BYTES:
                raise ValueError("job set record or byte limit exceeded")

    def _refresh_job_sources(self, report):
        """Stage published HDFS runs before discovery, if any are configured.

        A failure here leaves `self._job_roots` as it was. The runs already
        staged stay readable, so a NameNode outage costs new inputs, not the
        ones C has been computing on.
        """

        if self.job_source_refresh is None:
            return
        try:
            self._job_roots = tuple(self.config.job_roots) + tuple(
                self.job_source_refresh()
            )
        except (ValueError, OSError, RuntimeError) as exc:
            report["failed"] += 1
            LOGGER.warning(
                "C job source refresh failed error_type=%s", type(exc).__name__
            )

    def _manifests(self):
        found = []
        visited = 0
        for root in self._job_roots:
            if (root / "manifest.json").is_file():
                found.append((root / "manifest.json", root))
            with os.scandir(root) as entries:
                for entry in entries:
                    visited += 1
                    if visited > self.config.max_manifests * 4:
                        raise ValueError("input directory discovery limit exceeded")
                    if entry.is_dir(follow_symlinks=False):
                        path = Path(entry.path) / "manifest.json"
                        if path.is_file():
                            found.append((path, root))
                    if len(found) > self.config.max_manifests:
                        raise ValueError("manifest discovery limit exceeded")
        return sorted(set(found))

    def poll_once(self):
        report = {"completed": 0, "failed": 0, "blocked": 0, "pending": 0}
        self._refresh_job_sources(report)
        outputs = []
        input_bindings = {}
        invalid_set = False
        try:
            manifests = self._manifests()
            if self.job_set_sink and self._known_manifests.keys() - set(manifests):
                raise ValueError("previously consumed completion manifest is missing")
        except (ValueError, OSError) as exc:
            report["failed"] += 1
            invalid_set = True
            manifests = ()
            LOGGER.warning(
                "C intake discovery failed error_type=%s", type(exc).__name__
            )
        for path, root in manifests:
            if self._stop.is_set():
                break
            try:
                loaded = load_job_output(path, root)
                if loaded.collection_issues:
                    report["blocked"] += 1
                    invalid_set = True
                    continue
                if self.job_set_sink:
                    binding = (loaded.batch_sha256, loaded.manifest_sha256)
                    known = self._known_manifests.get((path, root))
                    if known is not None and known != binding:
                        raise ValueError("verified completion input was replaced")
                    outputs.append(loaded)
                    input_bindings[(path, root)] = binding
                    continue
                for criteria in self.config.criteria:
                    if loaded.mixed_date_semantics and requires_original_posting_date(
                        criteria
                    ):
                        report["blocked"] += 1
                        continue
                    key = (
                        loaded.batch_sha256,
                        loaded.manifest_sha256,
                        digest(criteria.model_dump(mode="json")),
                    )
                    if key in self._completed:
                        continue
                    result = self.job_sink(loaded, criteria)
                    if result["status"] == "COMPLETED":
                        self._completed.add(key)
                        report["completed"] += 1
                    else:
                        report["pending"] += 1
            except (
                ValueError,
                OSError,
                RuntimeError,
                KeyError,
                TypeError,
                psycopg.Error,
            ) as exc:
                report["failed"] += 1
                invalid_set = True
                LOGGER.warning(
                    "C intake input failed error_type=%s", type(exc).__name__
                )
        if self.job_set_sink and not self._stop.is_set() and not invalid_set:
            try:
                self._validate_job_set_capacity(outputs)
                if self.job_input_guard:
                    self.job_input_guard(
                        {
                            os.path.normcase(str(path.resolve())): hashes
                            for (path, _), hashes in input_bindings.items()
                        }
                    )
                self._known_manifests.update(input_bindings)
            except (ValueError, OSError, RuntimeError, psycopg.Error) as exc:
                report["failed"] += 1
                invalid_set = True
                LOGGER.warning(
                    "C intake binding failed error_type=%s", type(exc).__name__
                )
        if self.job_set_sink and not self._stop.is_set():
            if invalid_set:
                with self._job_set_lock:
                    self._current_jobs = {}
                    self._verified_job_outputs = ()
                    self._verified_job_signature = None
            elif outputs:
                self._publish_input_set(outputs, report)
            else:
                with self._job_set_lock:
                    self._current_jobs = {}
                    self._verified_job_outputs = ()
                    self._verified_job_signature = None
                report["pending"] += len(self.config.criteria)
        self.last_report = report
        for index, sink in enumerate(self.public_sinks):
            if index in self._public_completed or self._stop.is_set():
                continue
            try:
                value = sink()
                self.public_reports[index] = value
                if value["status"] == "COMPLETED":
                    self._public_completed.add(index)
            except (
                ValueError,
                OSError,
                RuntimeError,
                KeyError,
                TypeError,
                psycopg.Error,
            ) as exc:
                self.public_reports[index] = {
                    "status": "FAILED",
                    "error_type": type(exc).__name__,
                }
                LOGGER.warning(
                    "C public intake failed source_index=%s error_type=%s",
                    index,
                    type(exc).__name__,
                )
        return report

    def _run(self):
        while not self._stop.is_set():
            try:
                self.poll_once()
            except (
                ValueError,
                OSError,
                RuntimeError,
                KeyError,
                TypeError,
                psycopg.Error,
            ) as exc:
                if self.job_set_sink:
                    with self._job_set_lock:
                        self._current_jobs = {}
                        self._verified_job_outputs = ()
                        self._verified_job_signature = None
                self.last_report = {
                    "completed": 0,
                    "failed": 1,
                    "blocked": 0,
                    "pending": 0,
                }
                LOGGER.warning(
                    "C intake discovery failed error_type=%s", type(exc).__name__
                )
            self._stop.wait(self.config.poll_seconds)

    def start(self):
        if self.running:
            raise RuntimeError("intake is already running")
        self._stop.clear()
        self._thread = Thread(
            target=self._run, name="c-completed-output-intake", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)


def configured_runner(path: Path, store: ComputeStore, mapper, registry):
    from functools import partial

    from worker.job_hdfs_source import refresher

    config = IntakeConfig.model_validate_json(_read(path, 1024 * 1024))
    # Either kind of job input feeds the same union, so the union sink and the
    # durable binding follow whichever is configured.
    has_job_inputs = bool(config.job_roots or config.job_hdfs_sources)
    return IntakeRunner(
        config,
        job_sink=partial(
            publish_job_output, store=store, mapper=mapper, registry=registry
        ),
        job_set_sink=partial(
            publish_job_input_set, store=store, mapper=mapper, registry=registry
        )
        if has_job_inputs
        else None,
        job_trend_sink=partial(
            publish_monthly_job_trends,
            store=store,
            mapper=mapper,
            registry=registry,
        )
        if has_job_inputs
        else None,
        job_input_guard=store.bind_job_inputs if has_job_inputs else None,
        job_source_refresh=refresher(config.job_hdfs_sources)
        if config.job_hdfs_sources
        else None,
        public_sinks=tuple(
            _PublicSource(source, store, registry) for source in config.public_sources
        ),
    )


class _PublicSource:
    """Load a fixed publication once per process, then resume one partition per poll."""

    def __init__(self, config, store, registry):
        self.config, self.store, self.registry = config, store, registry
        self.consumer = None
        self.reader = None

    def __call__(self):
        from github.artifact_reader import ReadOnlyWebHdfsReader
        from github.snapshot_input import load_published_snapshot
        from worker.public_intake import PublicPipelineConsumer

        if self.consumer is None:
            self.reader = ReadOnlyWebHdfsReader(
                self.config.namenode_base_url,
                self.config.root_uri,
                additional_uri_prefixes=self.config.artifact_root_uris,
                datanode_routes=self.config.datanode_routes,
                user=self.config.hdfs_user,
                max_requests=self.config.max_requests,
            )
            published = load_published_snapshot(self.config.root_uri, self.reader)
            self.consumer = PublicPipelineConsumer(
                published=published,
                reader=self.reader,
                registry=self.registry,
                checkpoint_dir=self.config.checkpoint_dir,
                registry_sha256=digest(self.registry.model_dump(mode="json")),
                store=self.store,
                include_partial=self.config.include_partial,
                max_records=self.config.max_records,
                max_declared_bytes=self.config.max_declared_bytes,
            )
        result = self.consumer.poll_once(max_new_partitions=1)
        return {**result, "reader_stats": dict(self.reader.stats)}
