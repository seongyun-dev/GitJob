"""Publish job-posting runs that are already in Raw to `analysis_input`.

`analysis_input.publish_from_env` runs inside the collector, immediately after
a successful Raw upload, and only ever sees the run it just wrote. That is the
right shape for new collection and the wrong shape for the runs collected
before it existed: those are in Raw and nowhere else.

    Raw     hdfs:///gitjob/raw/{source}/dt=YYYY-MM-DD/{RUN_ID}/   36 runs
    Publish hdfs:///gitjob/analysis_input/jobs/{source}/{RUN_ID}/  7 runs

Measured 2026-09-14. Of the 29 unpublished runs, roughly half have no local
directory at all — they predate the `collector-state` volume, so the collector
cannot republish them even if it were asked to. Backfill therefore reads Raw
rather than local disk.

### It publishes; it still does not merge

Every rule `analysis_input` states applies here unchanged. This module adds a
way to *find* runs and a way to *resume*, and nothing else. It does not
deduplicate, choose a latest observation, or write a combined view —
`job.input_union.build_input_union` owns that on C's side, and a second
implementation would be a second opinion about which posting wins. JobKorea
v3 full-active runs are included; C later keeps the latest complete scope for
active matching.

The gate is not restated either: `analysis_input.release_blockers` decides what
may be published, and a backfilled run is held back for exactly the reasons a
freshly collected one would be. An empty run, a stopped run, a manifest without
`output_sha256` — all stay in Raw, which is where the record of them belongs.

### Why the run is materialized to a temp directory

`release_blockers` and `publish_run` both read a local run directory, because
the collector always has one. Rather than grow a second HDFS-shaped path
through the gate — where the two could drift and the backfilled run would be
checked less carefully than the live one — the three files are downloaded to a
temp directory and handed to the same code. Batch size remains bounded by the
consumer contract; the directory is removed as soon as the run is published.

### Resume

A run that has been published is recorded in the checkpoint before the next one
starts. A backfill that dies halfway is restarted with the same command and
skips what it already did. The checkpoint is an optimisation, not the
correctness boundary: `store_immutable` already refuses to overwrite, so a run
republished after a lost checkpoint lands as `unchanged` rather than as
damage.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from common.webhdfs import (
    WebHdfsClient,
    WebHdfsError,
    normalize_hdfs_path,
)

from job.collector.analysis_input import (
    AnalysisInputPublishResult,
    JobPostingAnalysisInputPublisher,
    publisher_from_env,
    release_blockers,
)
from job.collector.raw_sink import DEFAULT_RAW_ROOT, RUN_FILENAMES, sink_from_env

__all__ = [
    "BACKFILL_CHECKPOINT",
    "BackfillCheckpoint",
    "BackfillOutcome",
    "BackfillSummary",
    "RawRun",
    "backfill_runs",
    "discover_raw_runs",
    "materialize_run",
]

BACKFILL_CHECKPOINT = "analysis_input_backfill.json"

# Sources admitted to C's shared job intake.  JobKorea v3 full-active runs use
# the same immutable promotion path after their partial-detail counts reconcile.
DEFAULT_SOURCES: tuple[str, ...] = (
    "worknet",
    "saramin",
    "career",
    "gamejob",
    "jobkorea",
)


@dataclass(frozen=True)
class RawRun:
    """One run directory found under Raw."""

    source: str
    pipeline_run_id: str
    raw_path: PurePosixPath

    @property
    def key(self) -> str:
        return f"{self.source}:{self.pipeline_run_id}"


@dataclass(frozen=True)
class BackfillOutcome:
    """What happened to one run."""

    run: RawRun
    state: str
    detail: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.run.source,
            "pipeline_run_id": self.run.pipeline_run_id,
            "raw_path": self.run.raw_path.as_posix(),
            "state": self.state,
            "detail": list(self.detail),
        }


@dataclass(frozen=True)
class BackfillSummary:
    outcomes: tuple[BackfillOutcome, ...] = ()
    dry_run: bool = False

    def by_state(self, state: str) -> tuple[BackfillOutcome, ...]:
        return tuple(o for o in self.outcomes if o.state == state)

    @property
    def ok(self) -> bool:
        return not self.by_state("FAILED")

    def as_dict(self) -> dict[str, object]:
        counts: dict[str, int] = {}
        for outcome in self.outcomes:
            counts[outcome.state] = counts.get(outcome.state, 0) + 1
        return {
            "dry_run": self.dry_run,
            "counts": counts,
            "runs": [outcome.as_dict() for outcome in self.outcomes],
            "recorded_at": datetime.now(UTC).isoformat(),
        }


@dataclass
class BackfillCheckpoint:
    """Run keys already published, so a resumed backfill skips them."""

    path: Path | None = None
    published: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path | None) -> BackfillCheckpoint:
        checkpoint = cls(path=path)
        if path is None or not path.exists():
            return checkpoint
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # An unreadable checkpoint costs re-verification, not damage:
            # `store_immutable` refuses to overwrite with different bytes.
            return checkpoint
        keys = raw.get("published") if isinstance(raw, Mapping) else None
        if isinstance(keys, list):
            checkpoint.published = {str(key) for key in keys}
        return checkpoint

    def remember(self, run: RawRun) -> None:
        self.published.add(run.key)

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "schema_version": "analysis-input-backfill/v1",
                    "updated_at": datetime.now(UTC).isoformat(),
                    "published": sorted(self.published),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)


def discover_raw_runs(
    client: WebHdfsClient,
    *,
    sources: Sequence[str] = DEFAULT_SOURCES,
    raw_root: str = DEFAULT_RAW_ROOT,
) -> tuple[RawRun, ...]:
    """Every run directory under `raw/{source}/dt=*/`, oldest partition first.

    Ordered so a backfill that is interrupted has published a contiguous span
    of history rather than a scatter, which makes "how far did it get" a
    question the partition name answers.
    """

    root = normalize_hdfs_path(raw_root)
    found: list[RawRun] = []
    for source in sources:
        site = source.strip().lower()
        if not site:
            continue
        source_root = root / site
        for partition in client.list_directories(source_root):
            partition_path = source_root / partition
            for run_id in client.list_directories(partition_path):
                found.append(
                    RawRun(
                        source=site,
                        pipeline_run_id=run_id,
                        raw_path=partition_path / run_id,
                    )
                )
    return tuple(found)


def materialize_run(client: WebHdfsClient, run: RawRun, into: Path) -> tuple[str, ...]:
    """Download the run's three files. Returns the names that were missing."""

    into.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    for filename in RUN_FILENAMES:
        try:
            content = client.read(run.raw_path / filename)
        except (WebHdfsError, OSError):
            missing.append(filename)
            continue
        (into / filename).write_bytes(content)
    return tuple(missing)


def _already_published(
    publisher: JobPostingAnalysisInputPublisher, run: RawRun
) -> bool:
    """Is the batch already under `analysis_input` for this run id?

    Checked before downloading so a resumed backfill whose checkpoint was lost
    costs one `GETFILESTATUS` per run instead of one full batch read.
    """

    from job.collector.analysis_input import BATCH_FILENAME, analysis_input_run_path

    destination = analysis_input_run_path(
        source=run.source,
        pipeline_run_id=run.pipeline_run_id,
        root=publisher.root,
    )
    try:
        return publisher.client.exists(destination / BATCH_FILENAME)
    except (WebHdfsError, OSError):
        return False


def backfill_runs(
    runs: Iterable[RawRun],
    *,
    reader: WebHdfsClient,
    publisher: JobPostingAnalysisInputPublisher,
    checkpoint: BackfillCheckpoint | None = None,
    dry_run: bool = False,
    workspace: Path | None = None,
) -> BackfillSummary:
    """Publish each run that passes the gate, recording what happened to all.

    A blocked or failed run never stops the pass. Backfill is one-off and
    unattended; stopping on the first run that C would have declined anyway
    would leave the rest of history unpublished for no gain.
    """

    outcomes: list[BackfillOutcome] = []
    for run in runs:
        if checkpoint is not None and run.key in checkpoint.published:
            outcomes.append(BackfillOutcome(run, "SKIPPED_CHECKPOINT"))
            continue
        if _already_published(publisher, run):
            # S15P21E102-357: a dry run reports, it does not remember. Recording
            # here regardless of `dry_run` meant reading the plan rewrote the
            # resume file, and the next dry run reported the same runs as
            # SKIPPED_CHECKPOINT instead of ALREADY_PUBLISHED -- a different
            # plan from the one the operator just approved.
            if checkpoint is not None and not dry_run:
                checkpoint.remember(run)
                checkpoint.save()
            outcomes.append(BackfillOutcome(run, "ALREADY_PUBLISHED"))
            continue

        staging = Path(workspace or tempfile.mkdtemp(prefix=f"backfill-{run.source}-"))
        run_dir = staging if workspace is None else staging / run.pipeline_run_id
        try:
            missing = materialize_run(reader, run, run_dir)
            if missing:
                outcomes.append(
                    BackfillOutcome(
                        run, "BLOCKED", tuple(f"MISSING_FILE:{m}" for m in missing)
                    )
                )
                continue

            blockers = release_blockers(
                run_dir, source=run.source, pipeline_run_id=run.pipeline_run_id
            )
            if blockers:
                outcomes.append(BackfillOutcome(run, "BLOCKED", blockers))
                continue

            if dry_run:
                outcomes.append(BackfillOutcome(run, "WOULD_PUBLISH"))
                continue

            result: AnalysisInputPublishResult = publisher.publish_run(
                run_dir, source=run.source, pipeline_run_id=run.pipeline_run_id
            )
            if result.ok:
                if checkpoint is not None:
                    checkpoint.remember(run)
                    checkpoint.save()
                outcomes.append(BackfillOutcome(run, "PUBLISHED"))
            else:
                outcomes.append(
                    BackfillOutcome(
                        run,
                        "FAILED",
                        tuple(str(entry.get("error", "")) for entry in result.failed),
                    )
                )
        finally:
            if workspace is None:
                shutil.rmtree(staging, ignore_errors=True)

    return BackfillSummary(outcomes=tuple(outcomes), dry_run=dry_run)


def backfill_from_env(
    *,
    sources: Sequence[str] = DEFAULT_SOURCES,
    checkpoint_path: Path | None = None,
    dry_run: bool = False,
) -> BackfillSummary | None:
    """Build both clients from the environment, or return None without WebHDFS."""

    publisher = publisher_from_env()
    sink = sink_from_env()
    if publisher is None or sink is None:
        return None
    runs = discover_raw_runs(sink.client, sources=sources, raw_root=sink.raw_root)
    return backfill_runs(
        runs,
        reader=sink.client,
        publisher=publisher,
        checkpoint=BackfillCheckpoint.load(checkpoint_path),
        dry_run=dry_run,
    )
