"""Bring A's published job runs from HDFS to the existing local intake (S15P21E102-220).

A publishes verified collector runs to an immutable path:

```
hdfs:///gitjob/analysis_input/jobs/<source>/<RUN_ID>/
    job_analysis_input.json · postings.csv · manifest.json
```

C's completed-output intake reads local directories. `IntakeConfig.job_roots` is
`tuple[Path, ...]` and its validator requires existing directories, `_manifests`
uses `os.scandir`, and `load_job_output` compares `stat()` identity before and
after reading. None of that can be pointed at an `hdfs://` URI.

So this module downloads a run and hands the existing loader ordinary files.

### Why materialize instead of teaching the loader to read HDFS

`load_job_output` proves the producer did not rewrite the output underneath it:
it stamps `(st_dev, st_ino, st_size, st_mtime_ns)` for the manifest and the
batch, reads both, then re-stamps and re-reads the manifest. Those are local
filesystem guarantees. Reimplementing that check over WebHDFS would mean a
second, weaker copy of the rule that decides whether an input is trustworthy —
and `build_input_union` is documented as a pure function that "never reads a
file or URI". Giving it the same `JobOutput` values it already receives keeps
the semantics identical by construction rather than by careful re-derivation.

### Not a sync daemon

There is no background copier and no sidecar. `IntakeRunner.poll_once` asks for
a refresh at the start of each poll, so a run is fetched the first time C is
about to look for work and never again. Already-materialized runs are skipped by
the presence of their manifest, so repeated polling is free and idempotent.

### C never writes to HDFS

The transport is `ReadOnlyWebHdfsReader`, which is GET-only, pinned to one URI
namespace, bounded in bytes and request count, and refuses redirects it was not
configured for. Nothing here can modify the published run.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from common.webhdfs import WebHdfsError
from pydantic import BaseModel, ConfigDict, Field, model_validator

LOGGER = logging.getLogger(__name__)

# What A publishes, and what C needs beside a manifest. `manifest.json` is the
# completion marker and is written into the staging directory last.
RUN_FILENAMES: tuple[str, ...] = (
    "job_analysis_input.json",
    "postings.csv",
    "manifest.json",
)
BATCH_FILENAME = "job_analysis_input.json"
MANIFEST_FILENAME = "manifest.json"

# Downloads land here before being moved into place. It is a sibling of the
# per-source roots, never inside one: `_manifests` scans one level below each
# root, so a half-written run under a root could be picked up mid-write and
# then vanish when the move completed — which `poll_once` reports as a
# previously consumed manifest going missing.
INCOMING_DIRNAME = ".incoming"


class JobHdfsSourceConfig(BaseModel):
    """One published jobs namespace and the local directory it is staged into.

    Shaped like `PublicInputConfig` in `worker.intake`, which configures the
    GitHub public snapshot source, so an operator editing `c-intake.json` sees
    one pattern rather than two.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    root_uri: str
    namenode_base_url: str
    datanode_routes: dict[str, str] = Field(default_factory=dict)
    hdfs_user: str = "hadoop"
    # Absolute local directory. One sub-directory per source is created here and
    # those become the intake roots.
    staging_dir: Path
    sources: tuple[str, ...] = Field(min_length=1, max_length=16)
    max_runs_per_source: int = Field(default=200, ge=1, le=10_000, strict=True)
    max_batch_bytes: int = Field(
        default=64 * 1024 * 1024, ge=1, le=64 * 1024 * 1024, strict=True
    )
    max_manifest_bytes: int = Field(
        default=4 * 1024 * 1024, ge=1, le=8 * 1024 * 1024, strict=True
    )
    max_requests: int = Field(default=8000, ge=1, le=100_000, strict=True)

    @model_validator(mode="after")
    def validate_source(self):
        if not self.staging_dir.is_absolute():
            raise ValueError("staging directory must be absolute")
        for source in self.sources:
            if not source or source != Path(source).name or source in {".", ".."}:
                raise ValueError("each source must be a single path component")
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("duplicate source")
        # Constructing the reader validates the namespace, origin and routes
        # here rather than at the first poll.
        self._reader()
        return self

    def _reader(self):
        from github.artifact_reader import ReadOnlyWebHdfsReader

        return ReadOnlyWebHdfsReader(
            self.namenode_base_url,
            self.root_uri,
            datanode_routes=self.datanode_routes,
            user=self.hdfs_user,
            max_requests=self.max_requests,
        )

    def source_root(self, source: str) -> Path:
        return self.staging_dir / source


class JobHdfsRunSource:
    """Materializes published runs for one namespace, once each."""

    def __init__(self, config: JobHdfsSourceConfig, *, reader=None):
        self.config = config
        self.reader = reader if reader is not None else config._reader()

    def materialize(self) -> tuple[Path, ...]:
        """Fetch every complete run not staged yet; return the intake roots.

        Roots are returned even when nothing could be fetched. A WebHDFS outage
        must leave the runs already staged readable — C keeps computing on what
        it has instead of losing its inputs because the NameNode blinked.
        """

        incoming = self.config.staging_dir / INCOMING_DIRNAME
        incoming.mkdir(parents=True, exist_ok=True)

        roots = []
        for source in self.config.sources:
            root = self.config.source_root(source)
            root.mkdir(parents=True, exist_ok=True)
            roots.append(root)
            try:
                self._materialize_source(source, root, incoming)
            except (WebHdfsError, OSError) as error:
                LOGGER.warning(
                    "C job HDFS source unavailable source=%s error_type=%s",
                    source,
                    type(error).__name__,
                )
        return tuple(roots)

    def _materialize_source(self, source: str, root: Path, incoming: Path) -> None:
        listed = self.reader.list_directory(f"{self.config.root_uri}/{source}")
        run_ids = [
            entry["pathSuffix"] for entry in listed if entry.get("type") == "DIRECTORY"
        ]
        for run_id in sorted(run_ids)[: self.config.max_runs_per_source]:
            if (root / run_id / MANIFEST_FILENAME).is_file():
                # Already staged. Re-reading it would spend the request budget
                # to produce bytes C has already bound to a computed result.
                continue
            try:
                self._fetch_run(source, run_id, root, incoming)
            except (WebHdfsError, OSError, TypeError, ValueError) as error:
                LOGGER.warning(
                    "C job run not staged source=%s run=%s error_type=%s",
                    source,
                    run_id,
                    type(error).__name__,
                )

    def _fetch_run(self, source: str, run_id: str, root: Path, incoming: Path) -> None:
        base = f"{self.config.root_uri}/{source}/{run_id}"

        # The manifest is the completion marker. A run directory without one is
        # not finished being published, so it is not an error and not fetched.
        manifest_raw = self.reader.read(
            f"{base}/{MANIFEST_FILENAME}", max_bytes=self.config.max_manifest_bytes
        )
        manifest = _manifest_object(manifest_raw)

        batch_raw = self.reader.read(
            f"{base}/{BATCH_FILENAME}", max_bytes=self.config.max_batch_bytes
        )
        declared = manifest.get("output_sha256")
        if not isinstance(declared, dict):
            raise TypeError("manifest does not bind its outputs")
        if declared.get(BATCH_FILENAME) != hashlib.sha256(batch_raw).hexdigest():
            # The published bytes and the manifest disagree. Staging them would
            # only move the contradiction to a place C trusts more.
            raise ValueError("published batch does not match the manifest checksum")

        postings_raw = self.reader.read(
            f"{base}/postings.csv", max_bytes=self.config.max_batch_bytes
        )

        staged = incoming / f"{source}-{run_id}-{uuid.uuid4().hex}"
        try:
            staged.mkdir(parents=True)
            (staged / BATCH_FILENAME).write_bytes(batch_raw)
            (staged / "postings.csv").write_bytes(postings_raw)
            (staged / MANIFEST_FILENAME).write_bytes(manifest_raw)
            # One rename publishes the whole run: the loader can never observe a
            # manifest without the batch beside it.
            os.replace(staged, root / run_id)
        except OSError:
            shutil.rmtree(staged, ignore_errors=True)
            raise


def _manifest_object(raw: bytes) -> dict[str, Any]:
    try:
        manifest = json.loads(raw)
    except ValueError as error:
        raise ValueError("manifest is not valid JSON") from error
    if not isinstance(manifest, dict):
        raise TypeError("manifest must be an object")
    return manifest


def refresher(sources: tuple[JobHdfsSourceConfig, ...], *, reader=None):
    """Build the callable `IntakeRunner` invokes at the start of each poll."""

    materializers = tuple(JobHdfsRunSource(config, reader=reader) for config in sources)

    def refresh() -> tuple[Path, ...]:
        roots: list[Path] = []
        for materializer in materializers:
            roots.extend(materializer.materialize())
        return tuple(roots)

    return refresh
