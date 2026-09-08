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
from datetime import datetime
from pathlib import Path
from threading import Event, Thread
from typing import Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from job.cohort import CohortCriteria
from job.contracts import JobAnalysisInputBatch
from worker.lease import LeaseHeartbeat
from worker.store import ComputeStore, digest

LOGGER = logging.getLogger(__name__)
INTAKE_VERSION = "c-completed-output-intake/v1"
MAX_JOB_SET_BYTES = 128 * 1024 * 1024
MAX_JOB_SET_RECORDS = 50_000


class PublicInputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    root_uri: str
    namenode_base_url: str
    datanode_routes: dict[str, str] = Field(default_factory=dict)
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
    public_sources: tuple[PublicInputConfig, ...] = Field(default=(), max_length=4)
    poll_seconds: int = Field(default=30, ge=1, le=3600, strict=True)
    max_manifests: int = Field(default=1000, ge=1, le=10000, strict=True)

    @model_validator(mode="after")
    def configured_sources(self):
        if not self.job_roots and not self.public_sources:
            raise ValueError("at least one completed input source is required")
        if bool(self.job_roots) != bool(self.criteria):
            raise ValueError(
                "job roots and cohort criteria must be configured together"
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


def load_job_output(manifest_path: Path, root: Path) -> JobOutput:
    manifest_path = _contained(manifest_path, root)
    if manifest_path.name != "manifest.json":
        raise ValueError("only the producer completion manifest is accepted")
    manifest_before = _stamp(manifest_path)
    manifest_raw = _read(manifest_path, 1024 * 1024)
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
    batch_name = (
        "job_analysis_input_v1.json"
        if manifest.get("source", {}).get("site") == "JOBKOREA"
        else "job_analysis_input.json"
    )
    batch_path = _contained(manifest_path.parent / batch_name, root)
    before = manifest_before, _stamp(batch_path)
    batch_raw = _read(batch_path, 32 * 1024 * 1024)
    batch = JobAnalysisInputBatch.model_validate_json(batch_raw)
    if manifest.get("outputs", {}).get(batch_name) != batch_name:
        raise ValueError("manifest output must name the fixed sibling batch")
    if (
        before != (_stamp(manifest_path), _stamp(batch_path))
        or _read(manifest_path, 1024 * 1024) != manifest_raw
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
    if manifest.get("source", {}).get("site") == "JOBKOREA":
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
        for field, code in (
            ("detail_errors", "DETAIL_COLLECTION_FAILED"),
            ("invalid_records", "INVALID_SOURCE_RECORDS"),
        ):
            if manifest["counts"].get(field, 0):
                issues.append(code)
    for key in ("collector_version", "pipeline_run_id"):
        if metadata.get(key) != getattr(batch, key):
            raise ValueError("manifest identity does not match the batch")
    occurred_at = datetime.fromisoformat(metadata["collected_at"])
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("manifest timestamp requires a timezone")
    if type(count) is not int or count != len(batch.records):
        raise ValueError("manifest record count does not match the batch")
    if source not in ("SARAMIN", "WORKNET", "JOBKOREA") or any(
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
    )


def publish_job_output(
    loaded: JobOutput, criteria: CohortCriteria, *, store, mapper, registry
):
    from worker.api import compute_versions
    from worker.jobs import job_artifacts

    if loaded.collection_issues:
        raise ValueError("incomplete collection requires quality-aware review")
    if loaded.mixed_date_semantics and (criteria.posted_from or criteria.posted_to):
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
    from job.demand import aggregate_demand
    from job.input_union import build_input_union
    from worker.api import compute_versions
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
            results = store.complete(
                ticket,
                [
                    Artifact("COHORT", None, cohort.model_dump(mode="json"), identity),
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


class IntakeRunner:
    def __init__(
        self,
        config: IntakeConfig,
        *,
        job_sink: Callable,
        public_sinks: tuple[Callable, ...] = (),
        job_set_sink: Callable | None = None,
        job_input_guard: Callable | None = None,
    ):
        self.config, self.job_sink = config, job_sink
        self.public_sinks = public_sinks
        self.job_set_sink = job_set_sink
        self.job_input_guard = job_input_guard
        self._current_jobs = {}
        self._job_set_cache = {}
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
        return self._current_jobs.get(digest(criteria.model_dump(mode="json")))

    def _publish_input_set(self, outputs, report):
        signature = digest(
            sorted({(value.batch_sha256, value.manifest_sha256) for value in outputs})
        )
        current = {}
        for criteria in self.config.criteria:
            if self._stop.is_set():
                return
            key = digest(criteria.model_dump(mode="json"))
            relevant = [
                value
                for value in outputs
                if not criteria.sources or value.source_site in criteria.sources
            ]
            if not relevant:
                report["pending"] += 1
                continue
            if any(value.mixed_date_semantics for value in relevant) and (
                criteria.posted_from or criteria.posted_to
            ):
                report["blocked"] += 1
                continue
            try:
                cached = self._job_set_cache.get(key)
                if cached and cached[0] == signature:
                    current[key] = cached[1]
                    continue
                result = self.job_set_sink(tuple(relevant), criteria)
                if result["status"] == "COMPLETED":
                    self._job_set_cache[key] = (signature, result)
                    current[key] = result
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
                LOGGER.warning("C input union failed error_type=%s", type(exc).__name__)
        self._current_jobs = current

    def _manifests(self):
        found = []
        visited = 0
        for root in self.config.job_roots:
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
        outputs = []
        input_bindings = {}
        input_bytes = input_records = 0
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
                    input_bytes += loaded.batch_size_bytes
                    input_records += len(loaded.batch.records)
                    if (
                        input_bytes > MAX_JOB_SET_BYTES
                        or input_records > MAX_JOB_SET_RECORDS
                    ):
                        report["failed"] += 1
                        invalid_set = True
                        break
                    outputs.append(loaded)
                    input_bindings[(path, root)] = binding
                    continue
                for criteria in self.config.criteria:
                    if loaded.mixed_date_semantics and (
                        criteria.posted_from or criteria.posted_to
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
                self._current_jobs = {}
            elif outputs:
                self._publish_input_set(outputs, report)
            else:
                self._current_jobs = {}
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
                    self._current_jobs = {}
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

    config = IntakeConfig.model_validate_json(_read(path, 1024 * 1024))
    return IntakeRunner(
        config,
        job_sink=partial(
            publish_job_output, store=store, mapper=mapper, registry=registry
        ),
        job_set_sink=partial(
            publish_job_input_set, store=store, mapper=mapper, registry=registry
        )
        if config.job_roots
        else None,
        job_input_guard=store.bind_job_inputs if config.job_roots else None,
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
