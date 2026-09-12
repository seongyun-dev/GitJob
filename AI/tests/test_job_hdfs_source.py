"""Published HDFS job runs reach the existing local intake unchanged (S15P21E102-220).

No network: a fake reader serves bytes produced by the real collector writer, so
what C stages is what A publishes. The point of every case here is that the
adapter is transport only — the same `JobOutput` values and the same
`build_input_union` result must come out either way.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from test_compute_api import REGISTRY
from test_job_cohort import batch, criteria, posting

from common.webhdfs import WebHdfsError
from job.input_union import build_input_union
from registry.mapper import RegistryMapper
from Saramin_Collector_V1.crawler import CrawlResult, write_outputs
from worker.intake import IntakeConfig, IntakeRunner, load_job_output
from worker.job_hdfs_source import (
    JobHdfsRunSource,
    JobHdfsSourceConfig,
    refresher,
)

ROOT_URI = "hdfs:///gitjob/analysis_input/jobs"
NAMENODE = "http://hdfs-namenode:9870/webhdfs/v1"
SOURCES = ("worknet", "saramin", "career", "gamejob")
SITE = {
    "worknet": "WORKNET",
    "saramin": "SARAMIN",
    "career": "CAREER",
    "gamejob": "GAMEJOB",
}


def published_run(directory: Path, source: str, identifier: str) -> Path:
    """Write one run exactly as the collector writes it, then return its dir."""

    value = batch(
        posting(
            identifier, source_site=SITE[source], collected_at="2026-09-07T00:00:00Z"
        )
    ).model_copy(
        update={"pipeline_run_id": uuid4().hex, "dataset_snapshot_id": uuid4().hex}
    )
    manifest = {
        "schema_version": value.schema_version,
        "dataset_snapshot_id": value.dataset_snapshot_id,
        "pipeline_run_id": value.pipeline_run_id,
        "collector_version": value.collector_version,
        "source_site": SITE[source],
        "collected_at": value.records[0].collected_at.isoformat(),
        "counts": {"records": 1},
        "stopped_reason": None,
    }
    paths = write_outputs(CrawlResult(value, manifest), directory)
    return paths["manifest"].parent


class FakeReader:
    """An in-memory published namespace with the reader's public surface."""

    def __init__(self, tree: dict[str, dict[str, bytes]] | None = None):
        # `<source>/<run_id>` -> {filename: bytes}
        self.tree: dict[str, dict[str, bytes]] = tree or {}
        self.reads: list[str] = []
        self.fail_listing: set[str] = set()
        self.fail_read: set[str] = set()

    def publish(self, source: str, run_dir: Path) -> str:
        run_id = run_dir.name
        self.tree[f"{source}/{run_id}"] = {
            item.name: item.read_bytes() for item in sorted(run_dir.iterdir())
        }
        return run_id

    def _relative(self, uri: str) -> str:
        assert uri.startswith(ROOT_URI + "/"), uri
        return uri[len(ROOT_URI) + 1 :]

    def list_directory(self, uri: str, *, max_entries: int = 4096):
        source = self._relative(uri)
        if source in self.fail_listing:
            raise WebHdfsError("listing unavailable")
        runs = sorted(
            key.split("/", 1)[1] for key in self.tree if key.split("/", 1)[0] == source
        )
        return tuple(
            {"pathSuffix": run, "type": "DIRECTORY", "length": 0} for run in runs
        )

    def read(self, uri: str, *, max_bytes: int) -> bytes:
        relative = self._relative(uri)
        if relative in self.fail_read:
            raise WebHdfsError("read unavailable")
        self.reads.append(relative)
        source, run_id, filename = relative.split("/")
        files = self.tree.get(f"{source}/{run_id}", {})
        if filename not in files:
            raise WebHdfsError("no such object")
        payload = files[filename]
        if len(payload) > max_bytes:
            raise WebHdfsError("object exceeds the configured byte limit")
        return payload


def source_config(tmp_path: Path, *, sources=SOURCES) -> JobHdfsSourceConfig:
    return JobHdfsSourceConfig(
        root_uri=ROOT_URI,
        namenode_base_url=NAMENODE,
        staging_dir=tmp_path / "staging",
        sources=tuple(sources),
    )


@pytest.fixture
def published(tmp_path):
    """Four sources, one run each, as A would have published them."""

    origin = tmp_path / "origin"
    reader = FakeReader()
    runs = {}
    for index, source in enumerate(SOURCES):
        run_dir = published_run(origin / source, source, f"posting-{index}")
        runs[source] = reader.publish(source, run_dir)
    return reader, runs


def test_every_configured_source_is_discovered_and_staged(tmp_path, published):
    reader, runs = published
    config = source_config(tmp_path)

    roots = JobHdfsRunSource(config, reader=reader).materialize()

    assert [root.name for root in roots] == list(SOURCES)
    for source in SOURCES:
        staged = config.source_root(source) / runs[source]
        assert sorted(item.name for item in staged.iterdir()) == [
            "job_analysis_input.json",
            "manifest.json",
            "postings.csv",
        ]


def test_staged_runs_load_through_the_existing_loader(tmp_path, published):
    reader, runs = published
    config = source_config(tmp_path)

    JobHdfsRunSource(config, reader=reader).materialize()

    for source in SOURCES:
        root = config.source_root(source)
        loaded = load_job_output(root / runs[source] / "manifest.json", root)
        assert loaded.source_site == SITE[source]
        assert loaded.collection_issues == ()


def test_union_is_identical_to_reading_the_same_runs_locally(tmp_path, published):
    """The adapter is transport. The cohort must not depend on how bytes arrived."""

    reader, runs = published
    origin = tmp_path / "origin"
    mapper = RegistryMapper(REGISTRY)
    query = criteria()

    local_outputs = tuple(
        load_job_output(
            origin / source / runs[source] / "manifest.json", origin / source
        )
        for source in SOURCES
    )

    config = source_config(tmp_path)
    JobHdfsRunSource(config, reader=reader).materialize()
    staged_outputs = tuple(
        load_job_output(
            config.source_root(source) / runs[source] / "manifest.json",
            config.source_root(source),
        )
        for source in SOURCES
    )

    local = build_input_union(local_outputs, query, mapper)
    staged = build_input_union(staged_outputs, query, mapper)

    assert staged.model_dump(mode="json") == local.model_dump(mode="json")


def test_a_run_without_a_manifest_is_ignored(tmp_path, published):
    reader, runs = published
    del reader.tree["worknet/" + runs["worknet"]]["manifest.json"]
    config = source_config(tmp_path)

    JobHdfsRunSource(config, reader=reader).materialize()

    # The incomplete run is skipped; the other three still arrive.
    assert not (config.source_root("worknet") / runs["worknet"]).exists()
    for source in ("saramin", "career", "gamejob"):
        assert (config.source_root(source) / runs[source] / "manifest.json").is_file()


def test_a_batch_that_does_not_match_the_manifest_checksum_is_refused(
    tmp_path, published
):
    reader, runs = published
    key = "saramin/" + runs["saramin"]
    reader.tree[key]["job_analysis_input.json"] = b'{"records": "tampered"}'
    config = source_config(tmp_path)

    JobHdfsRunSource(config, reader=reader).materialize()

    assert not (config.source_root("saramin") / runs["saramin"]).exists()
    # Nothing partial is left behind either.
    assert list((config.staging_dir / ".incoming").iterdir()) == []


def test_a_manifest_without_output_binding_is_refused(tmp_path, published):
    reader, runs = published
    key = "career/" + runs["career"]
    manifest = json.loads(reader.tree[key]["manifest.json"])
    manifest.pop("output_sha256")
    reader.tree[key]["manifest.json"] = json.dumps(manifest).encode()
    config = source_config(tmp_path)

    JobHdfsRunSource(config, reader=reader).materialize()

    assert not (config.source_root("career") / runs["career"]).exists()


def test_repeated_materialize_does_not_refetch_or_duplicate(tmp_path, published):
    reader, _ = published
    config = source_config(tmp_path)
    materializer = JobHdfsRunSource(config, reader=reader)

    materializer.materialize()
    first_reads = len(reader.reads)
    staged = {
        source: sorted(p.name for p in config.source_root(source).iterdir())
        for source in SOURCES
    }

    materializer.materialize()
    materializer.materialize()

    assert len(reader.reads) == first_reads, "a staged run was fetched again"
    assert {
        source: sorted(p.name for p in config.source_root(source).iterdir())
        for source in SOURCES
    } == staged


def test_a_new_run_appearing_later_is_picked_up(tmp_path, published):
    reader, runs = published
    config = source_config(tmp_path)
    materializer = JobHdfsRunSource(config, reader=reader)
    materializer.materialize()

    later = published_run(tmp_path / "origin2" / "worknet", "worknet", "posting-later")
    second = reader.publish("worknet", later)

    materializer.materialize()

    assert (config.source_root("worknet") / second / "manifest.json").is_file()
    assert (config.source_root("worknet") / runs["worknet"] / "manifest.json").is_file()


def test_a_listing_outage_keeps_previously_staged_runs(tmp_path, published):
    reader, runs = published
    config = source_config(tmp_path)
    materializer = JobHdfsRunSource(config, reader=reader)
    materializer.materialize()

    reader.fail_listing = set(SOURCES)
    roots = materializer.materialize()

    # Roots are still returned and the staged runs are untouched.
    assert [root.name for root in roots] == list(SOURCES)
    for source in SOURCES:
        assert (config.source_root(source) / runs[source] / "manifest.json").is_file()


def test_a_read_outage_leaves_no_partial_run(tmp_path, published):
    reader, runs = published
    reader.fail_read = {f"gamejob/{runs['gamejob']}/postings.csv"}
    config = source_config(tmp_path)

    JobHdfsRunSource(config, reader=reader).materialize()

    assert not (config.source_root("gamejob") / runs["gamejob"]).exists()
    assert list((config.staging_dir / ".incoming").iterdir()) == []


def test_runner_refreshes_roots_before_discovery(tmp_path, published):
    """The runner must see runs that only exist on HDFS when the poll starts."""

    reader, _ = published
    config = source_config(tmp_path)
    loaded = []

    intake = IntakeConfig(
        schema_version="c-intake-config/v1",
        criteria=(criteria(),),
        job_hdfs_sources=(config,),
    )
    runner = IntakeRunner(
        intake,
        job_sink=lambda output, _criteria: (
            loaded.append(output) or {"status": "COMPLETED", "results": []}
        ),
        job_source_refresh=refresher((config,), reader=reader),
    )

    report = runner.poll_once()

    assert report["failed"] == 0
    assert sorted(output.source_site for output in loaded) == sorted(SITE.values())


def test_runner_keeps_local_roots_alongside_hdfs_sources(tmp_path, published):
    """Configuring an HDFS source must not disable plain local roots."""

    reader, _ = published
    local_root = tmp_path / "local"
    local_root.mkdir()
    published_run(local_root, "saramin", "local-posting")
    config = source_config(tmp_path)
    loaded = []

    intake = IntakeConfig(
        schema_version="c-intake-config/v1",
        job_roots=(local_root,),
        criteria=(criteria(),),
        job_hdfs_sources=(config,),
    )
    runner = IntakeRunner(
        intake,
        job_sink=lambda output, _criteria: (
            loaded.append(output) or {"status": "COMPLETED", "results": []}
        ),
        job_source_refresh=refresher((config,), reader=reader),
    )

    runner.poll_once()

    # Four staged sources plus the local run.
    assert len(loaded) == len(SOURCES) + 1


def test_refresh_failure_is_reported_without_losing_known_roots(tmp_path):
    config = source_config(tmp_path)
    intake = IntakeConfig(
        schema_version="c-intake-config/v1",
        criteria=(criteria(),),
        job_hdfs_sources=(config,),
    )

    def refresh():
        raise OSError("staging volume unavailable")

    runner = IntakeRunner(
        intake,
        job_sink=lambda *_: {"status": "COMPLETED", "results": []},
        job_source_refresh=refresh,
    )
    runner._job_roots = (tmp_path / "already-staged",)
    (tmp_path / "already-staged").mkdir()

    report = runner.poll_once()

    assert report["failed"] >= 1
    assert runner._job_roots == (tmp_path / "already-staged",)


def test_configuration_rejects_unusable_sources(tmp_path):
    with pytest.raises(ValueError):
        JobHdfsSourceConfig(
            root_uri=ROOT_URI,
            namenode_base_url=NAMENODE,
            staging_dir=Path("relative/staging"),
            sources=("worknet",),
        )
    with pytest.raises(ValueError):
        source_config(tmp_path, sources=("worknet/../raw",))
    with pytest.raises(ValueError):
        source_config(tmp_path, sources=("worknet", "worknet"))


def test_job_inputs_require_criteria(tmp_path):
    with pytest.raises(ValueError):
        IntakeConfig(
            schema_version="c-intake-config/v1",
            job_hdfs_sources=(source_config(tmp_path),),
        )


def test_local_only_configuration_still_validates(tmp_path):
    """The configuration that existed before this change must keep working."""

    local_root = tmp_path / "local"
    local_root.mkdir()
    config = IntakeConfig(
        schema_version="c-intake-config/v1",
        job_roots=(local_root,),
        criteria=(criteria(),),
    )
    assert config.job_hdfs_sources == ()
    runner = IntakeRunner(config, job_sink=lambda *_: {"status": "COMPLETED"})
    assert runner._job_roots == (local_root,)
