"""Publish a collected job-posting run to the HDFS Raw layer (S15P21E102-99).

The path rule and the transport are S15P21E102-110's, reused rather than
redefined: `/gitjob/raw/{source}/dt=YYYY-MM-DD/` and the NameNode WebHDFS HTTP
API through `common.webhdfs.WebHdfsClient`. `docs/data/README.md` records that
contract, including the correction from an earlier `/raw/{source}/dt=`.

### Raw only — Parquet is a downstream step

S15P21E102-99 words this as "Snapshot을 HDFS/Parquet에 직접 적재", but the
collector image carries no Parquet writer, and `collector/gharchive/sinks.py`
states why it stays that way: the image is a slim Python runtime with neither a
Hadoop CLI nor a JRE. GH Archive already publishes untouched bytes to Raw and
leaves the columnar conversion to a later stage, so job postings follow the
same shape instead of making one pipeline the exception. Confirm with the
S15P21E102-110 owner before adding a Parquet writer here.

### The partition is `collected_at`, not `posted_at`

One batch file holds records with many different `posted_at` values — a run
with `--days-back 1` deliberately spans two registration dates — so a *file*
cannot be partitioned by a per-record field. Raw therefore partitions by when
the run collected, which is also what GH Archive's `dt=` means. Grouping by
registration date is an analysis-layer concern and belongs to the Parquet and
serving tables (S15P21E102-146).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from common.webhdfs import WebHdfsClient, WebHdfsError, normalize_hdfs_path

__all__ = [
    "DEFAULT_RAW_ROOT",
    "RAW_UPLOAD_RECORD",
    "RUN_FILENAMES",
    "JobPostingRawSink",
    "RawUploadResult",
    "raw_run_path",
    "sink_from_env",
]

# Matches `RAW_ROOT` in `.env.example` and `Infra/compose/compose.yaml`.
DEFAULT_RAW_ROOT = "hdfs:///gitjob/raw"

# What a collector run writes locally, in the order they are published. The
# batch goes first so a reader that sees `manifest.json` can rely on the batch
# already being there.
RUN_FILENAMES: tuple[str, ...] = (
    "job_analysis_input.json",
    "postings.csv",
    "manifest.json",
)

# Written into the local run directory, not uploaded: a record of where the
# run went, so the upload can be audited without querying HDFS.
RAW_UPLOAD_RECORD = "raw_upload.json"


@dataclass(frozen=True)
class RawUploadResult:
    """What happened to one run's files."""

    run_path: str
    uploaded: tuple[str, ...] = ()
    # Already present with identical bytes. A re-run of the same
    # `pipeline_run_id` is expected to land here, not to fail.
    unchanged: tuple[str, ...] = ()
    failed: tuple[dict[str, str], ...] = ()

    @property
    def ok(self) -> bool:
        return not self.failed

    def as_dict(self) -> dict[str, object]:
        return {
            "run_path": self.run_path,
            "uploaded": list(self.uploaded),
            "unchanged": list(self.unchanged),
            "failed": [dict(entry) for entry in self.failed],
            "recorded_at": datetime.now(UTC).isoformat(),
        }


def raw_run_path(
    *,
    source: str,
    collected_at: datetime,
    pipeline_run_id: str,
    raw_root: str = DEFAULT_RAW_ROOT,
) -> PurePosixPath:
    """Build the Raw directory for one run.

    `/gitjob/raw/{source}/dt=YYYY-MM-DD/{pipeline_run_id}/`

    GH Archive puts its files directly under `dt=`, because one hour is one
    file. A collector run is three files that only make sense together — the
    manifest describes the batch beside it — so the run id becomes a directory
    instead of being folded into each filename.
    """

    if collected_at.tzinfo is None:
        raise ValueError("collected_at must include a timezone")
    day = collected_at.astimezone(UTC)

    partition_source = source.strip().lower()
    _require_single_segment(partition_source, "source")
    _require_single_segment(pipeline_run_id.strip(), "pipeline_run_id")

    root = normalize_hdfs_path(raw_root)
    return root / partition_source / f"dt={day:%Y-%m-%d}" / pipeline_run_id.strip()


def _require_single_segment(value: str, label: str) -> None:
    if not value:
        raise ValueError(f"{label} must not be blank")
    if PurePosixPath(value).name != value or value in {".", ".."}:
        raise ValueError(f"{label} must be a single path component: {value!r}")


@dataclass(frozen=True)
class JobPostingRawSink:
    """Publish a run directory to Raw, immutably.

    Upload failures are returned, never raised. The local snapshot was already
    written and postings cannot be collected again, so losing the run over a
    NameNode hiccup is the one outcome worth designing against.
    """

    client: WebHdfsClient
    raw_root: str = DEFAULT_RAW_ROOT
    filenames: tuple[str, ...] = field(default=RUN_FILENAMES)

    def upload_run(
        self,
        run_dir: Path,
        *,
        source: str,
        collected_at: datetime,
        pipeline_run_id: str,
    ) -> RawUploadResult:
        destination = raw_run_path(
            source=source,
            collected_at=collected_at,
            pipeline_run_id=pipeline_run_id,
            raw_root=self.raw_root,
        )
        uploaded: list[str] = []
        unchanged: list[str] = []
        failed: list[dict[str, str]] = []

        for filename in self.filenames:
            local = run_dir / filename
            if not local.exists():
                failed.append({"file": filename, "error": "local file missing"})
                continue
            target = destination / filename
            try:
                existed = self.client.exists(target)
                uri = self.client.store_immutable(target, local.read_bytes())
            except FileExistsError:
                # Same path, different bytes: a run id was reused for different
                # data. Overwriting would destroy an earlier snapshot, so this
                # is reported rather than resolved.
                failed.append(
                    {
                        "file": filename,
                        "error": "raw object exists with different content",
                    }
                )
            except (WebHdfsError, OSError) as error:
                failed.append({"file": filename, "error": str(error)[:400]})
            else:
                (unchanged if existed else uploaded).append(uri)

        return RawUploadResult(
            run_path=destination.as_posix(),
            uploaded=tuple(uploaded),
            unchanged=tuple(unchanged),
            failed=tuple(failed),
        )


def sink_from_env(
    env: Mapping[str, str] | None = None,
) -> JobPostingRawSink | None:
    """Build a sink from the environment, or None when HDFS is not configured.

    `WEBHDFS_URL` is the switch. `Infra/compose/compose.yaml` injects it for
    the deployed collector, and a developer without a NameNode gets a
    local-only run instead of a failure — which is why this returns None
    rather than raising.
    """

    values = os.environ if env is None else env
    base_url = (values.get("WEBHDFS_URL") or "").strip()
    if not base_url:
        return None
    return JobPostingRawSink(
        client=WebHdfsClient(
            base_url=base_url,
            user=(values.get("WEBHDFS_USER") or "hadoop").strip() or "hadoop",
        ),
        raw_root=(values.get("RAW_ROOT") or DEFAULT_RAW_ROOT).strip()
        or DEFAULT_RAW_ROOT,
    )


def write_upload_record(run_dir: Path, result: RawUploadResult) -> Path:
    """Leave a local note of where the run was published."""

    path = run_dir / RAW_UPLOAD_RECORD
    path.write_text(
        json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
