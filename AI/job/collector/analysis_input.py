"""Publish verified collector runs to the C-facing `analysis_input` path (S15P21E102-220).

```
Raw     hdfs:///gitjob/raw/{source}/dt=YYYY-MM-DD/{RUN_ID}/     (unchanged)
Publish hdfs:///gitjob/analysis_input/jobs/{source}/{RUN_ID}/   (this module)
```

Raw keeps every run, including the ones that stopped early or collected
nothing, because Raw is the record of what happened. `analysis_input` is a
different promise: everything under it is a run C may compute on without
re-deriving whether it is trustworthy. So the same three files are published a
second time rather than C being pointed at Raw and told which run directories
to skip.

### A publishes runs; A does not merge them

This module writes one run to one immutable directory. It does not build a
current/upsert view, deduplicate across runs, or decide which posting is the
latest. `docs/ai/c-compute-runtime.md` places that with C — "자동 실행은 지정된
roots 의 검증된 완료 입력 관측 합집합을 C에서 만든다. A에 새로운 통합 batch 를
요구하지 않는다" — and `job.input_union.build_input_union` already implements
it (`SELECTED` / `SUPERSEDED` / `DUPLICATE` / `AFTER_AS_OF` over
`source_record_id` and `collected_at`). Nothing here may grow into a second
opinion about which record wins.

### The gate mirrors what C already refuses

`worker.intake.load_job_output` rejects an input whose manifest reports an
early stop, detail failures or invalid records, and refuses a manifest whose
`output_sha256` does not bind the batch bytes. Publishing such a run would put
a file under `analysis_input` that C then declines — a promise broken at the
only place that promise exists. The checks are restated here rather than
imported because `worker` is C's package and pulls in psycopg, which the slim
collector image does not carry.

The upload loop itself is not restated: `raw_sink.upload_run_files` owns it, so
immutability and the reused-run-id rule cannot drift between the two paths.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from common.webhdfs import (
    WebHdfsClient,
    WebHdfsError,
    normalize_hdfs_path,
    parse_datanode_hosts,
)
from job.collector.raw_sink import (
    RUN_FILENAMES,
    RawUploadResult,
    require_single_segment,
    upload_run_files,
)

__all__ = [
    "ANALYSIS_INPUT_PUBLISH_RECORD",
    "DEFAULT_ANALYSIS_INPUT_ROOT",
    "AnalysisInputPublishResult",
    "JobPostingAnalysisInputPublisher",
    "analysis_input_run_path",
    "publish_from_env",
    "publisher_from_env",
    "release_blockers",
    "write_publish_record",
]

# Matches `ANALYSIS_INPUT_JOBS_ROOT` in `.env.example` and
# `Infra/compose/compose.yaml`. The GitHub side already publishes under
# `analysis_input/github/repo_snapshot/`, so jobs take the sibling namespace.
DEFAULT_ANALYSIS_INPUT_ROOT = "hdfs:///gitjob/analysis_input/jobs"

# Written into the local run directory beside `raw_upload.json`, not uploaded.
ANALYSIS_INPUT_PUBLISH_RECORD = "analysis_input_publish.json"

# The batch filename C looks for beside a manifest. JobKorea's `_v1` variant is
# not handled here: that collector was discarded (S15P21E102-195) and the four
# scheduled sources all write this name.
BATCH_FILENAME = "job_analysis_input.json"


@dataclass(frozen=True)
class AnalysisInputPublishResult:
    """What happened to one run's publication.

    `blockers` non-empty means nothing was uploaded — the run was refused
    before any byte moved, which is the only safe order when the destination is
    supposed to contain trustworthy runs only.
    """

    run_path: str
    blockers: tuple[str, ...] = ()
    published: tuple[str, ...] = ()
    # Already present with identical bytes: re-publishing the same run id with
    # the same content is expected to land here, not to fail.
    unchanged: tuple[str, ...] = ()
    failed: tuple[dict[str, str], ...] = ()
    read_back: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.blockers and not self.failed

    @property
    def skipped(self) -> bool:
        return bool(self.blockers)

    def as_dict(self) -> dict[str, object]:
        return {
            "run_path": self.run_path,
            "blockers": list(self.blockers),
            "published": list(self.published),
            "unchanged": list(self.unchanged),
            "failed": [dict(entry) for entry in self.failed],
            "read_back": list(self.read_back),
            "recorded_at": datetime.now(UTC).isoformat(),
        }


def analysis_input_run_path(
    *,
    source: str,
    pipeline_run_id: str,
    root: str = DEFAULT_ANALYSIS_INPUT_ROOT,
) -> PurePosixPath:
    """Build the publication directory for one run.

    `/gitjob/analysis_input/jobs/{source}/{RUN_ID}/`

    No `dt=` partition, unlike Raw. Raw partitions by collection day because it
    accumulates every run forever and needs a pruning boundary. This path is
    read by a consumer that lists run directories under one root per source, so
    an extra level would only make that listing deeper.
    """

    partition_source = source.strip().lower()
    require_single_segment(partition_source, "source")
    require_single_segment(pipeline_run_id.strip(), "pipeline_run_id")

    return normalize_hdfs_path(root) / partition_source / pipeline_run_id.strip()


def _load_manifest(run_dir: Path) -> dict[str, object] | None:
    try:
        raw = (run_dir / "manifest.json").read_bytes()
    except OSError:
        return None
    try:
        manifest = json.loads(raw)
    except ValueError:
        return None
    return manifest if isinstance(manifest, dict) else None


def _count(manifest: Mapping[str, object], field_name: str) -> int:
    counts = manifest.get("counts")
    if not isinstance(counts, Mapping):
        return 0
    value = counts.get(field_name)
    return value if type(value) is int else 0


def release_blockers(
    run_dir: Path,
    *,
    source: str,
    pipeline_run_id: str,
) -> tuple[str, ...]:
    """Reasons this run must not be published, or an empty tuple.

    Restates `worker.intake.load_job_output`'s refusals so a run that C would
    decline never reaches `analysis_input`. See the module docstring for why it
    is restated rather than imported.
    """

    blockers: list[str] = []

    for filename in RUN_FILENAMES:
        if not (run_dir / filename).is_file():
            blockers.append(f"MISSING_FILE:{filename}")
    if blockers:
        # Without the three files there is nothing to check against.
        return tuple(blockers)

    manifest = _load_manifest(run_dir)
    if manifest is None:
        return ("MANIFEST_UNREADABLE",)

    outputs = manifest.get("outputs")
    if (
        not isinstance(outputs, Mapping)
        or outputs.get(BATCH_FILENAME) != BATCH_FILENAME
    ):
        blockers.append("MANIFEST_OUTPUT_MISMATCH")

    declared = manifest.get("output_sha256")
    if declared is None:
        # C treats an unbound manifest as "hold, do not auto-publish".
        blockers.append("UNBOUND_LEGACY_MANIFEST")
    elif not isinstance(declared, Mapping):
        blockers.append("MANIFEST_OUTPUT_MISMATCH")
    else:
        batch_bytes = (run_dir / BATCH_FILENAME).read_bytes()
        if declared.get(BATCH_FILENAME) != hashlib.sha256(batch_bytes).hexdigest():
            blockers.append("BATCH_CHECKSUM_MISMATCH")

    declared_source = manifest.get("source_site")
    declared_run = manifest.get("pipeline_run_id")
    if (
        not isinstance(declared_source, str)
        or declared_source.strip().upper() != source.strip().upper()
        or declared_run != pipeline_run_id
    ):
        blockers.append("IDENTITY_MISMATCH")

    if manifest.get("stopped_reason"):
        blockers.append("COLLECTOR_STOPPED_EARLY")
    if _count(manifest, "detail_errors"):
        blockers.append("DETAIL_COLLECTION_FAILED")
    if _count(manifest, "invalid_records"):
        blockers.append("INVALID_SOURCE_RECORDS")
    if _count(manifest, "records") <= 0:
        # `RunOutcome.EMPTY` is deliberately not `SUCCESS` in the scheduler.
        blockers.append("EMPTY_RUN")

    return tuple(sorted(set(blockers)))


@dataclass(frozen=True)
class JobPostingAnalysisInputPublisher:
    """Publish a verified run directory to `analysis_input`, immutably.

    Failures are returned rather than raised, matching `JobPostingRawSink`: the
    local snapshot and Raw both already hold the run, so a NameNode hiccup here
    must be visible without discarding anything.
    """

    client: WebHdfsClient
    root: str = DEFAULT_ANALYSIS_INPUT_ROOT
    filenames: tuple[str, ...] = field(default=RUN_FILENAMES)

    def publish_run(
        self,
        run_dir: Path,
        *,
        source: str,
        pipeline_run_id: str,
    ) -> AnalysisInputPublishResult:
        destination = analysis_input_run_path(
            source=source,
            pipeline_run_id=pipeline_run_id,
            root=self.root,
        )

        blockers = release_blockers(
            run_dir, source=source, pipeline_run_id=pipeline_run_id
        )
        if blockers:
            return AnalysisInputPublishResult(
                run_path=destination.as_posix(), blockers=blockers
            )

        uploaded: RawUploadResult = upload_run_files(
            self.client, destination, run_dir, self.filenames
        )
        if not uploaded.ok:
            return AnalysisInputPublishResult(
                run_path=uploaded.run_path,
                published=uploaded.uploaded,
                unchanged=uploaded.unchanged,
                failed=uploaded.failed,
            )

        read_back, failures = self._read_back(destination, run_dir)
        return AnalysisInputPublishResult(
            run_path=uploaded.run_path,
            published=uploaded.uploaded,
            unchanged=uploaded.unchanged,
            failed=tuple(failures),
            read_back=tuple(read_back),
        )

    def _read_back(
        self, destination: PurePosixPath, run_dir: Path
    ) -> tuple[list[str], list[dict[str, str]]]:
        """Re-read every published object and compare it to the local bytes.

        `raw_verify` deliberately checks length instead, because re-reading a
        34 MB batch on every archive check costs more than it proves. This runs
        once per published run and guards the handover itself, so it compares
        content: a byte-for-byte match is the whole claim `analysis_input`
        makes to C.
        """

        verified: list[str] = []
        failures: list[dict[str, str]] = []
        for filename in self.filenames:
            target = destination / filename
            try:
                remote = self.client.read(target)
            except (WebHdfsError, OSError) as error:
                failures.append(
                    {"file": filename, "error": f"read-back failed: {str(error)[:360]}"}
                )
                continue
            if remote != (run_dir / filename).read_bytes():
                failures.append(
                    {"file": filename, "error": "read-back content mismatch"}
                )
            else:
                verified.append(target.as_posix())
        return verified, failures


def publisher_from_env(
    env: Mapping[str, str] | None = None,
) -> JobPostingAnalysisInputPublisher | None:
    """Build a publisher from the environment, or None when HDFS is absent.

    `WEBHDFS_URL` is the switch, the same one `raw_sink.sink_from_env` uses: a
    developer without a NameNode gets a local-only run instead of a failure.
    """

    values = os.environ if env is None else env
    base_url = (values.get("WEBHDFS_URL") or "").strip()
    if not base_url:
        return None
    root = (values.get("ANALYSIS_INPUT_JOBS_ROOT") or "").strip()
    return JobPostingAnalysisInputPublisher(
        client=WebHdfsClient(
            base_url=base_url,
            user=(values.get("WEBHDFS_USER") or "hadoop").strip() or "hadoop",
            datanode_hosts=parse_datanode_hosts(values.get("WEBHDFS_DATANODE_HOSTS")),
        ),
        root=root or DEFAULT_ANALYSIS_INPUT_ROOT,
    )


def write_publish_record(run_dir: Path, result: AnalysisInputPublishResult) -> Path:
    """Leave a local note of what was published, or why nothing was."""

    path = run_dir / ANALYSIS_INPUT_PUBLISH_RECORD
    path.write_text(
        json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def publish_from_env(
    run_dir: Path,
    *,
    source: str,
    pipeline_run_id: str,
) -> AnalysisInputPublishResult | None:
    """Publish one run using the environment, leaving the local record behind.

    Returns None when WebHDFS is not configured, matching
    `raw_sink.sink_from_env`. The four collectors call this immediately after a
    successful Raw upload, so the whole chain — collect, Raw, verify, publish —
    is one process with one exit code rather than a separate scheduled step
    that could run against a half-written run directory.
    """

    publisher = publisher_from_env()
    if publisher is None:
        return None
    result = publisher.publish_run(
        run_dir, source=source, pipeline_run_id=pipeline_run_id
    )
    write_publish_record(run_dir, result)
    return result
