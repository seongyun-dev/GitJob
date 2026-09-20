"""Publishing runs that are already in Raw (S15P21E102-220 follow-up).

The gate itself is covered by `test_job_analysis_input.py`; these exercise the
two things backfill adds — finding runs in HDFS, and resuming.
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from common.webhdfs import WebHdfsClient, WebHdfsResponse
from job.collector.analysis_input import JobPostingAnalysisInputPublisher
from job.collector.backfill import (
    BackfillCheckpoint,
    RawRun,
    backfill_runs,
    discover_raw_runs,
    materialize_run,
)
from job.jobkorea_contract import JOBKOREA_V3_DUTY_ROLE_PAIRS

BASE_URL = "http://hdfs-namenode:9870/webhdfs/v1"
DATANODE = "http://hdfs-datanode:9864/upload"


def _boolean(value: bool) -> bytes:
    return json.dumps({"boolean": value}).encode()


def _run_files(
    *,
    source: str,
    run_id: str,
    records: int = 3,
    stopped_reason: str | None = None,
    bind_batch: bool = True,
    batch_body: str = "batch",
) -> dict[str, bytes]:
    batch = json.dumps({"records": batch_body}, ensure_ascii=False).encode()
    manifest: dict[str, object] = {
        "schema_version": "job-analysis-input/v1",
        "source_site": source.upper(),
        "collector_version": f"{source}/1.0.0",
        "pipeline_run_id": run_id,
        "dataset_snapshot_id": f"ds_{source}",
        "collected_at": "2026-09-09T00:10:00+00:00",
        "counts": {"records": records, "detail_errors": 0, "invalid_records": 0},
        "stopped_reason": stopped_reason,
        "outputs": {"job_analysis_input.json": "job_analysis_input.json"},
    }
    if bind_batch:
        manifest["output_sha256"] = {
            "job_analysis_input.json": hashlib.sha256(batch).hexdigest()
        }
    return {
        "job_analysis_input.json": batch,
        "postings.csv": b"id,title,source_url,raw_job_category\n1,backend,http://x,BACKEND\n",
        "manifest.json": json.dumps(manifest, ensure_ascii=False).encode(),
    }


@dataclass
class FakeHdfs:
    """In-memory WebHDFS with LISTSTATUS, mirroring the real two-step CREATE."""

    stored: dict[str, bytes] = field(default_factory=dict)
    fail_create_for: tuple[str, ...] = ()
    calls: list[tuple[str, str]] = field(default_factory=list)

    def seed_run(self, source: str, partition: str, run_id: str, **kwargs) -> None:
        for name, content in _run_files(source=source, run_id=run_id, **kwargs).items():
            self.stored[f"/gitjob/raw/{source}/{partition}/{run_id}/{name}"] = content

    def _children(self, path: str) -> list[str]:
        prefix = path.rstrip("/") + "/"
        names = set()
        for key in self.stored:
            if key.startswith(prefix):
                names.add(key[len(prefix) :].split("/", 1)[0])
        # A name with nothing under it is a file, not a directory.
        return sorted(
            name
            for name in names
            if any(key.startswith(prefix + name + "/") for key in self.stored)
        )

    def request(self, method, url, *, body=None, timeout):
        assert timeout > 0
        self.calls.append((method, url))

        if url.startswith(DATANODE):
            target = urllib.parse.unquote(url.split("path=", 1)[1])
            self.stored[target] = body if isinstance(body, bytes) else b""
            return WebHdfsResponse(201, {}, b"")

        path = urllib.parse.unquote(url.split("/webhdfs/v1", 1)[1].split("?", 1)[0])
        operation = url.rsplit("op=", 1)[1].split("&", 1)[0]

        if operation == "LISTSTATUS":
            children = self._children(path)
            if not children and not any(
                key.startswith(path.rstrip("/") + "/") for key in self.stored
            ):
                return WebHdfsResponse(404, {}, b'{"RemoteException":{}}')
            payload = {
                "FileStatuses": {
                    "FileStatus": [
                        {"pathSuffix": name, "type": "DIRECTORY"} for name in children
                    ]
                }
            }
            return WebHdfsResponse(200, {}, json.dumps(payload).encode())
        if operation == "GETFILESTATUS":
            if path in self.stored:
                return WebHdfsResponse(200, {}, b'{"FileStatus":{"length":0}}')
            return WebHdfsResponse(404, {}, b'{"RemoteException":{}}')
        if operation == "MKDIRS":
            return WebHdfsResponse(200, {}, _boolean(True))
        if operation == "OPEN":
            if path not in self.stored:
                return WebHdfsResponse(404, {}, b'{"RemoteException":{}}')
            return WebHdfsResponse(200, {}, self.stored[path])
        if operation == "CREATE":
            if any(marker in path for marker in self.fail_create_for):
                return WebHdfsResponse(500, {}, b"boom")
            location = f"{DATANODE}?path={urllib.parse.quote(path, safe='')}"
            return WebHdfsResponse(307, {"Location": location}, b"")
        if operation == "RENAME":
            destination = urllib.parse.unquote(
                url.rsplit("destination=", 1)[1].split("&", 1)[0]
            )
            content = self.stored.pop(path, None)
            if content is None:
                return WebHdfsResponse(200, {}, _boolean(False))
            self.stored[destination] = content
            return WebHdfsResponse(200, {}, _boolean(True))
        if operation == "DELETE":
            self.stored.pop(path, None)
            return WebHdfsResponse(200, {}, _boolean(True))
        raise AssertionError(f"unexpected WebHDFS operation: {operation}")


def _client(hdfs: FakeHdfs) -> WebHdfsClient:
    return WebHdfsClient(base_url=BASE_URL, transport=hdfs)


def _published(hdfs: FakeHdfs) -> list[str]:
    return sorted(k for k in hdfs.stored if k.startswith("/gitjob/analysis_input/"))


def _run(hdfs: FakeHdfs, **kwargs):
    client = _client(hdfs)
    return backfill_runs(
        discover_raw_runs(client),
        reader=client,
        publisher=JobPostingAnalysisInputPublisher(client=client),
        **kwargs,
    )


# -- discovery --------------------------------------------------------------


def test_discovery_walks_every_source_and_partition():
    hdfs = FakeHdfs()
    hdfs.seed_run("saramin", "dt=2026-09-09", "SARAMIN-A")
    hdfs.seed_run("saramin", "dt=2026-09-10", "SARAMIN-B")
    hdfs.seed_run("worknet", "dt=2026-09-09", "WORKNET-A")

    runs = discover_raw_runs(_client(hdfs))

    assert [r.key for r in runs] == [
        "worknet:WORKNET-A",
        "saramin:SARAMIN-A",
        "saramin:SARAMIN-B",
    ]


def test_discovery_is_ordered_oldest_partition_first():
    hdfs = FakeHdfs()
    hdfs.seed_run("career", "dt=2026-09-11", "CAREER-LATE")
    hdfs.seed_run("career", "dt=2026-09-09", "CAREER-EARLY")

    runs = [r.pipeline_run_id for r in discover_raw_runs(_client(hdfs))]

    assert runs == ["CAREER-EARLY", "CAREER-LATE"]


def test_a_source_that_never_collected_is_not_an_error():
    hdfs = FakeHdfs()
    hdfs.seed_run("saramin", "dt=2026-09-09", "SARAMIN-A")

    assert len(discover_raw_runs(_client(hdfs))) == 1


def test_jobkorea_is_discovered_for_v3_analysis_input_promotion():

    hdfs = FakeHdfs()
    hdfs.seed_run("jobkorea", "dt=2026-09-09", "JOBKOREA-A")

    runs = discover_raw_runs(_client(hdfs))

    assert [(run.source, run.pipeline_run_id) for run in runs] == [
        ("jobkorea", "JOBKOREA-A")
    ]


def test_listing_drops_files_and_keeps_directories():
    hdfs = FakeHdfs()
    hdfs.seed_run("saramin", "dt=2026-09-09", "SARAMIN-A")

    names = _client(hdfs).list_directories("/gitjob/raw/saramin/dt=2026-09-09")

    assert names == ("SARAMIN-A",)


def test_listing_a_missing_path_is_empty():
    assert _client(FakeHdfs()).list_directories("/gitjob/raw/nothing") == ()


# -- materialize ------------------------------------------------------------


def test_materialize_downloads_the_three_files(tmp_path: Path):
    hdfs = FakeHdfs()
    hdfs.seed_run("saramin", "dt=2026-09-09", "SARAMIN-A")
    run = discover_raw_runs(_client(hdfs))[0]

    missing = materialize_run(_client(hdfs), run, tmp_path / "run")

    assert missing == ()
    assert sorted(p.name for p in (tmp_path / "run").iterdir()) == [
        "job_analysis_input.json",
        "manifest.json",
        "postings.csv",
    ]


def test_materialize_reports_a_file_that_is_not_in_raw(tmp_path: Path):
    hdfs = FakeHdfs()
    hdfs.seed_run("saramin", "dt=2026-09-09", "SARAMIN-A")
    del hdfs.stored["/gitjob/raw/saramin/dt=2026-09-09/SARAMIN-A/postings.csv"]
    run = discover_raw_runs(_client(hdfs))[0]

    assert materialize_run(_client(hdfs), run, tmp_path / "run") == ("postings.csv",)


# -- publishing -------------------------------------------------------------


def test_a_healthy_run_is_published_under_its_source_and_run_id():
    hdfs = FakeHdfs()
    hdfs.seed_run("saramin", "dt=2026-09-09", "SARAMIN-A")

    summary = _run(hdfs)

    assert [o.state for o in summary.outcomes] == ["PUBLISHED"]
    assert _published(hdfs) == [
        "/gitjob/analysis_input/jobs/saramin/SARAMIN-A/job_analysis_input.json",
        "/gitjob/analysis_input/jobs/saramin/SARAMIN-A/manifest.json",
        "/gitjob/analysis_input/jobs/saramin/SARAMIN-A/postings.csv",
    ]


def test_published_bytes_are_the_raw_bytes():
    """Nothing is re-derived, so every field survives — url, category, body."""

    hdfs = FakeHdfs()
    hdfs.seed_run("career", "dt=2026-09-09", "CAREER-A")
    raw_prefix = "/gitjob/raw/career/dt=2026-09-09/CAREER-A"
    published_prefix = "/gitjob/analysis_input/jobs/career/CAREER-A"

    _run(hdfs)

    for name in ("job_analysis_input.json", "postings.csv", "manifest.json"):
        assert (
            hdfs.stored[f"{published_prefix}/{name}"]
            == hdfs.stored[f"{raw_prefix}/{name}"]
        )


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"records": 0}, "EMPTY_RUN"),
        ({"stopped_reason": "blocked"}, "COLLECTOR_STOPPED_EARLY"),
        ({"bind_batch": False}, "UNBOUND_LEGACY_MANIFEST"),
    ],
)
def test_a_run_c_would_decline_is_not_published(kwargs, expected):
    hdfs = FakeHdfs()
    hdfs.seed_run("worknet", "dt=2026-09-09", "WORKNET-A", **kwargs)

    summary = _run(hdfs)

    assert summary.outcomes[0].state == "BLOCKED"
    assert expected in summary.outcomes[0].detail
    assert _published(hdfs) == []


def _jobkorea_v3_manifest(run_id: str, *, scope_reason: str) -> dict[str, object]:
    """A v3 active-scope manifest, complete or not, in the producer's shape."""

    batch = json.dumps({"records": "batch"}, ensure_ascii=False).encode()
    scopes = [
        {
            "code": code,
            "name": code,
            "target_role": role,
            "scan_stop_reason": "short_page",
        }
        for code, role in sorted(JOBKOREA_V3_DUTY_ROLE_PAIRS)
    ]
    scopes[0]["scan_stop_reason"] = scope_reason
    run_reason = (
        "all_scopes_complete"
        if scope_reason in {"short_page", "empty_page"}
        else scope_reason
    )
    return {
        "schema_version": "job-analysis-input/v1",
        "source_site": "JOBKOREA",
        "collector_version": "jobkorea-crawler/v3",
        "pipeline_run_id": run_id,
        "dataset_snapshot_id": "JOBKOREA-2026-09-09-2026-09-09",
        "collected_at": "2026-09-09T00:10:00+00:00",
        "counts": {"records": 3, "detail_errors": 0, "invalid_records": 0},
        "stopped_reason": None,
        "outputs": {"job_analysis_input.json": "job_analysis_input.json"},
        "output_sha256": {"job_analysis_input.json": hashlib.sha256(batch).hexdigest()},
        "source": {"site": "JOBKOREA", "mode": "active_listing", "duty_scopes": scopes},
        "stats": {"scan_stop_reason": run_reason},
    }


def _seed_jobkorea_v3(hdfs: FakeHdfs, run_id: str, *, scope_reason: str) -> None:
    files = _run_files(source="jobkorea", run_id=run_id)
    files["manifest.json"] = json.dumps(
        _jobkorea_v3_manifest(run_id, scope_reason=scope_reason),
        ensure_ascii=False,
    ).encode()
    for name, content in files.items():
        hdfs.stored[f"/gitjob/raw/jobkorea/dt=2026-09-09/{run_id}/{name}"] = content


def test_a_complete_v3_run_is_published_without_a_second_crawl():
    """The publish-only half of S15P21E102-340.

    An 11-hour v3 crawl uploads Raw and stops. Approval then publishes from
    Raw, so the collection is never repeated.
    """

    hdfs = FakeHdfs()
    _seed_jobkorea_v3(hdfs, "JOBKOREA-V3-OK", scope_reason="short_page")

    summary = _run(hdfs)

    assert [o.state for o in summary.outcomes] == ["PUBLISHED"]
    assert _published(hdfs) != []


def test_a_v3_run_with_an_unanswered_scope_is_refused_by_publish_only():
    """`first_page_empty` must block here too, not only inside the crawler.

    Deferring publication moves the decision to this path, so the scope
    completeness gate has to hold on this side of the split as well.
    """

    hdfs = FakeHdfs()
    _seed_jobkorea_v3(hdfs, "JOBKOREA-V3-BLOCKED", scope_reason="first_page_empty")

    summary = _run(hdfs)

    assert [o.state for o in summary.outcomes] == ["BLOCKED"]
    assert _published(hdfs) == []


def test_one_blocked_run_does_not_stop_the_pass():
    hdfs = FakeHdfs()
    hdfs.seed_run("worknet", "dt=2026-09-09", "WORKNET-EMPTY", records=0)
    hdfs.seed_run("saramin", "dt=2026-09-09", "SARAMIN-OK")

    summary = _run(hdfs)

    assert {o.state for o in summary.outcomes} == {"BLOCKED", "PUBLISHED"}
    assert len(summary.by_state("PUBLISHED")) == 1


def test_lineage_keeps_the_raw_path_for_every_outcome():
    hdfs = FakeHdfs()
    hdfs.seed_run("gamejob", "dt=2026-09-08", "GAMEJOB-A")

    outcome = _run(hdfs).outcomes[0]

    assert outcome.as_dict()["raw_path"] == (
        "/gitjob/raw/gamejob/dt=2026-09-08/GAMEJOB-A"
    )
    assert outcome.as_dict()["source"] == "gamejob"


# -- idempotency and resume -------------------------------------------------


def test_a_second_pass_republishes_nothing():
    hdfs = FakeHdfs()
    hdfs.seed_run("saramin", "dt=2026-09-09", "SARAMIN-A")
    _run(hdfs)
    before = dict(hdfs.stored)

    summary = _run(hdfs)

    assert [o.state for o in summary.outcomes] == ["ALREADY_PUBLISHED"]
    assert hdfs.stored == before


def test_a_checkpointed_run_is_skipped_without_reading_it(tmp_path: Path):
    hdfs = FakeHdfs()
    hdfs.seed_run("saramin", "dt=2026-09-09", "SARAMIN-A")
    checkpoint = BackfillCheckpoint(path=tmp_path / "cp.json")
    checkpoint.remember(RawRun("saramin", "SARAMIN-A", None))  # type: ignore[arg-type]

    summary = _run(hdfs, checkpoint=checkpoint)

    assert [o.state for o in summary.outcomes] == ["SKIPPED_CHECKPOINT"]
    assert _published(hdfs) == []


def test_the_checkpoint_is_written_as_each_run_lands(tmp_path: Path):
    hdfs = FakeHdfs()
    hdfs.seed_run("saramin", "dt=2026-09-09", "SARAMIN-A")
    hdfs.seed_run("saramin", "dt=2026-09-10", "SARAMIN-B")
    path = tmp_path / "cp.json"

    _run(hdfs, checkpoint=BackfillCheckpoint.load(path))

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["published"] == ["saramin:SARAMIN-A", "saramin:SARAMIN-B"]


def test_a_resumed_pass_continues_from_the_checkpoint(tmp_path: Path):
    hdfs = FakeHdfs()
    hdfs.seed_run("saramin", "dt=2026-09-09", "SARAMIN-A")
    hdfs.seed_run("saramin", "dt=2026-09-10", "SARAMIN-B")
    path = tmp_path / "cp.json"

    # First pass fails on the second run's batch upload.
    hdfs.fail_create_for = ("SARAMIN-B",)
    first = _run(hdfs, checkpoint=BackfillCheckpoint.load(path))
    assert [o.state for o in first.outcomes] == ["PUBLISHED", "FAILED"]

    # The fault clears; the resumed pass skips the one already done.
    hdfs.fail_create_for = ()
    second = _run(hdfs, checkpoint=BackfillCheckpoint.load(path))

    assert [o.state for o in second.outcomes] == ["SKIPPED_CHECKPOINT", "PUBLISHED"]
    assert not second.by_state("FAILED")


def test_an_unreadable_checkpoint_costs_re_verification_not_damage(tmp_path: Path):
    hdfs = FakeHdfs()
    hdfs.seed_run("saramin", "dt=2026-09-09", "SARAMIN-A")
    _run(hdfs)
    path = tmp_path / "cp.json"
    path.write_text("{not json", encoding="utf-8")
    before = dict(hdfs.stored)

    summary = _run(hdfs, checkpoint=BackfillCheckpoint.load(path))

    assert [o.state for o in summary.outcomes] == ["ALREADY_PUBLISHED"]
    assert hdfs.stored == before


# -- dry run ----------------------------------------------------------------


def test_a_dry_run_writes_nothing():
    hdfs = FakeHdfs()
    hdfs.seed_run("saramin", "dt=2026-09-09", "SARAMIN-A")
    hdfs.seed_run("worknet", "dt=2026-09-09", "WORKNET-EMPTY", records=0)

    summary = _run(hdfs, dry_run=True)

    assert {o.state for o in summary.outcomes} == {"WOULD_PUBLISH", "BLOCKED"}
    assert _published(hdfs) == []


def test_a_dry_run_applies_the_same_gate():
    hdfs = FakeHdfs()
    hdfs.seed_run("worknet", "dt=2026-09-09", "WORKNET-A", stopped_reason="blocked")

    summary = _run(hdfs, dry_run=True)

    assert summary.outcomes[0].state == "BLOCKED"
    assert not summary.by_state("WOULD_PUBLISH")


# -- a dry run changes no durable state (S15P21E102-357) ----------------------
#
# `--dry-run` is the default posture and both the CLI docstring and the backfill
# runbook promise it writes nothing. The checkpoint was the exception: the
# ALREADY_PUBLISHED branch recorded and saved before the dry-run check, so
# simply *looking* rewrote the resume file. That silently moved runs from
# ALREADY_PUBLISHED to SKIPPED_CHECKPOINT on the next pass, which changes what
# an operator sees when they re-read a plan before approving it.


def test_a_dry_run_does_not_create_a_checkpoint(tmp_path: Path):
    hdfs = FakeHdfs()
    hdfs.seed_run("saramin", "dt=2026-09-09", "SARAMIN-A")
    path = tmp_path / "cp.json"

    _run(hdfs, checkpoint=BackfillCheckpoint.load(path), dry_run=True)

    assert not path.exists()


def test_a_dry_run_over_an_already_published_run_leaves_the_checkpoint_alone(
    tmp_path: Path,
):
    hdfs = FakeHdfs()
    hdfs.seed_run("saramin", "dt=2026-09-09", "SARAMIN-A")
    _run(hdfs)  # publish it for real
    path = tmp_path / "cp.json"
    path.write_text(json.dumps({"published": []}) + "\n", encoding="utf-8")
    before = path.read_bytes()

    summary = _run(hdfs, checkpoint=BackfillCheckpoint.load(path), dry_run=True)

    assert [o.state for o in summary.outcomes] == ["ALREADY_PUBLISHED"]
    assert path.read_bytes() == before


def test_a_dry_run_over_a_blocked_run_leaves_the_checkpoint_alone(tmp_path: Path):
    hdfs = FakeHdfs()
    hdfs.seed_run(
        "saramin", "dt=2026-09-09", "SARAMIN-A", stopped_reason="before_start_date"
    )
    path = tmp_path / "cp.json"
    path.write_text(json.dumps({"published": []}) + "\n", encoding="utf-8")
    before = path.read_bytes()

    summary = _run(hdfs, checkpoint=BackfillCheckpoint.load(path), dry_run=True)

    assert [o.state for o in summary.outcomes] == ["BLOCKED"]
    assert path.read_bytes() == before


def test_repeated_dry_runs_are_byte_identical(tmp_path: Path):
    """An operator re-reading the plan must see the same plan."""
    hdfs = FakeHdfs()
    hdfs.seed_run("saramin", "dt=2026-09-09", "SARAMIN-A")
    hdfs.seed_run("saramin", "dt=2026-09-10", "SARAMIN-B")
    _run(hdfs)  # both already published
    hdfs.seed_run("saramin", "dt=2026-09-11", "SARAMIN-C")
    path = tmp_path / "cp.json"

    first = _run(hdfs, checkpoint=BackfillCheckpoint.load(path), dry_run=True)
    second = _run(hdfs, checkpoint=BackfillCheckpoint.load(path), dry_run=True)

    assert [o.state for o in first.outcomes] == [o.state for o in second.outcomes]
    assert not path.exists()


def test_a_dry_run_never_publishes(tmp_path: Path):
    hdfs = FakeHdfs()
    hdfs.seed_run("saramin", "dt=2026-09-09", "SARAMIN-A")

    _run(hdfs, checkpoint=BackfillCheckpoint.load(tmp_path / "cp.json"), dry_run=True)

    assert _published(hdfs) == []


def test_execute_still_records_already_published_runs_in_the_checkpoint(
    tmp_path: Path,
):
    """The resume shortcut is the point of the checkpoint; only dry run is quiet."""
    hdfs = FakeHdfs()
    hdfs.seed_run("saramin", "dt=2026-09-09", "SARAMIN-A")
    _run(hdfs)
    path = tmp_path / "cp.json"

    summary = _run(hdfs, checkpoint=BackfillCheckpoint.load(path))

    assert [o.state for o in summary.outcomes] == ["ALREADY_PUBLISHED"]
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["published"] == ["saramin:SARAMIN-A"]
