"""HDFS Raw publishing for collector runs (S15P21E102-99).

No network: every case drives a recording fake transport, following
`test_gharchive_webhdfs_sink.py`.
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from common.webhdfs import WebHdfsClient, WebHdfsResponse
from job.collector.raw_sink import (
    DEFAULT_RAW_ROOT,
    RAW_UPLOAD_RECORD,
    RUN_FILENAMES,
    JobPostingRawSink,
    raw_run_path,
    sink_from_env,
    write_upload_record,
)

BASE_URL = "http://hdfs-namenode:9870/webhdfs/v1"
SEOUL = ZoneInfo("Asia/Seoul")
# 09:10 KST on the 7th is 00:10 UTC the same day, so the partition is stable
# across the two daily runs.
COLLECTED_AT = datetime(2026, 9, 7, 9, 10, tzinfo=SEOUL)
RUN_ID = "WORKNET-20260907T001000Z"


def _boolean(value: bool) -> bytes:
    return json.dumps({"boolean": value}).encode()


DATANODE = "http://hdfs-datanode:9864/upload"


@dataclass
class FakeTransport:
    """An in-memory WebHDFS.

    Mirrors the real two-step CREATE: the NameNode answers 307 with a
    datanode Location, and the bytes go to that Location.
    """

    stored: dict[str, bytes] = field(default_factory=dict)
    fail_create_for: tuple[str, ...] = ()
    calls: list[tuple[str, str]] = field(default_factory=list)

    def request(
        self,
        method: str,
        url: str,
        *,
        body: object | None = None,
        timeout: float,
    ) -> WebHdfsResponse:
        assert timeout > 0
        self.calls.append((method, url))

        if url.startswith(DATANODE):
            target = urllib.parse.unquote(url.split("path=", 1)[1])
            self.stored[target] = body if isinstance(body, bytes) else b""
            return WebHdfsResponse(201, {}, b"")

        path = urllib.parse.unquote(url.split("/webhdfs/v1", 1)[1].split("?", 1)[0])
        operation = url.rsplit("op=", 1)[1].split("&", 1)[0]

        if operation == "GETFILESTATUS":
            if path in self.stored:
                return WebHdfsResponse(200, {}, b'{"FileStatus":{}}')
            return WebHdfsResponse(404, {}, b'{"RemoteException":{}}')
        if operation == "MKDIRS":
            return WebHdfsResponse(200, {}, _boolean(True))
        if operation == "OPEN":
            return WebHdfsResponse(200, {}, self.stored.get(path, b""))
        if operation == "CREATE":
            if any(marker in path for marker in self.fail_create_for):
                return WebHdfsResponse(500, {}, b"boom")
            location = f"{DATANODE}?path={urllib.parse.quote(path, safe='')}"
            return WebHdfsResponse(307, {"Location": location}, b"")
        if operation == "RENAME":
            destination = urllib.parse.unquote(
                url.rsplit("destination=", 1)[1].split("&", 1)[0]
            )
            self.stored[destination] = self.stored.pop(path, b"")
            return WebHdfsResponse(200, {}, _boolean(True))
        if operation == "DELETE":
            self.stored.pop(path, None)
            return WebHdfsResponse(200, {}, _boolean(True))
        raise AssertionError(f"unexpected operation {operation}")


def _run_dir(tmp_path: Path, **overrides: str) -> Path:
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "job_analysis_input.json": '{"schema_version": "job-analysis-input/v1"}\n',
        "postings.csv": "source_record_id\nWORKNET:1\n",
        "manifest.json": '{"source_site": "WORKNET"}\n',
    }
    payload.update(overrides)
    for name, body in payload.items():
        (run_dir / name).write_text(body, encoding="utf-8")
    return run_dir


def _sink(transport: FakeTransport) -> JobPostingRawSink:
    return JobPostingRawSink(
        client=WebHdfsClient(base_url=BASE_URL, transport=transport)
    )


# --- the path rule is S15P21E102-110's ------------------------------------


def test_raw_path_follows_the_declared_layout():
    path = raw_run_path(
        source="WORKNET",
        collected_at=COLLECTED_AT,
        pipeline_run_id=RUN_ID,
    )
    assert path.as_posix() == f"/gitjob/raw/worknet/dt=2026-09-07/{RUN_ID}"


def test_source_is_lowercased_for_the_partition():
    """`source_site` is uppercase in the contract; the path segment is not."""

    path = raw_run_path(
        source="SARAMIN", collected_at=COLLECTED_AT, pipeline_run_id="SARAMIN-X"
    )
    assert "/saramin/" in path.as_posix()


def test_raw_root_accepts_the_hdfs_uri_form_used_in_env():
    path = raw_run_path(
        source="WORKNET",
        collected_at=COLLECTED_AT,
        pipeline_run_id=RUN_ID,
        raw_root="hdfs:///gitjob-ci/raw",
    )
    assert path.as_posix().startswith("/gitjob-ci/raw/worknet/")


def test_default_raw_root_matches_the_env_default():
    assert DEFAULT_RAW_ROOT == "hdfs:///gitjob/raw"


def test_partition_is_the_utc_day_of_collection():
    """An evening KST run must not slide into the next UTC day silently.

    21:10 KST is 12:10 UTC on the same date, so both daily runs share one
    partition — which is what makes a day's runs readable together.
    """

    morning = raw_run_path(
        source="WORKNET",
        collected_at=datetime(2026, 9, 7, 9, 10, tzinfo=SEOUL),
        pipeline_run_id="a",
    )
    evening = raw_run_path(
        source="WORKNET",
        collected_at=datetime(2026, 9, 7, 21, 10, tzinfo=SEOUL),
        pipeline_run_id="b",
    )
    assert "dt=2026-09-07" in morning.as_posix()
    assert "dt=2026-09-07" in evening.as_posix()


def test_naive_timestamp_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        raw_run_path(
            source="WORKNET",
            collected_at=datetime(2026, 9, 7, 9, 10),  # noqa: DTZ001
            pipeline_run_id=RUN_ID,
        )


@pytest.mark.parametrize("bad", ["../escape", "a/b", "", "."])
def test_path_traversal_in_the_run_id_is_rejected(bad: str):
    with pytest.raises(ValueError):
        raw_run_path(source="WORKNET", collected_at=COLLECTED_AT, pipeline_run_id=bad)


@pytest.mark.parametrize("bad", ["../x", "a/b", ""])
def test_path_traversal_in_the_source_is_rejected(bad: str):
    with pytest.raises(ValueError):
        raw_run_path(source=bad, collected_at=COLLECTED_AT, pipeline_run_id=RUN_ID)


# --- uploading a run -------------------------------------------------------


def test_a_run_publishes_all_three_files(tmp_path: Path):
    transport = FakeTransport()
    result = _sink(transport).upload_run(
        _run_dir(tmp_path),
        source="WORKNET",
        collected_at=COLLECTED_AT,
        pipeline_run_id=RUN_ID,
    )

    assert result.ok
    assert len(result.uploaded) == len(RUN_FILENAMES)
    for name in RUN_FILENAMES:
        assert f"/gitjob/raw/worknet/dt=2026-09-07/{RUN_ID}/{name}" in transport.stored


def test_the_batch_is_published_before_the_manifest(tmp_path: Path):
    """A reader that sees the manifest can rely on the batch being there."""

    transport = FakeTransport()
    _sink(transport).upload_run(
        _run_dir(tmp_path),
        source="WORKNET",
        collected_at=COLLECTED_AT,
        pipeline_run_id=RUN_ID,
    )
    renames = [
        url for method, url in transport.calls if method == "PUT" and "RENAME" in url
    ]
    order = [next(name for name in RUN_FILENAMES if name in url) for url in renames]
    assert order.index("job_analysis_input.json") < order.index("manifest.json")


def test_bytes_are_preserved_unchanged(tmp_path: Path):
    transport = FakeTransport()
    run_dir = _run_dir(tmp_path, **{"postings.csv": "제목,회사\n개발자,회사\n"})
    _sink(transport).upload_run(
        run_dir,
        source="WORKNET",
        collected_at=COLLECTED_AT,
        pipeline_run_id=RUN_ID,
    )
    stored = transport.stored[
        f"/gitjob/raw/worknet/dt=2026-09-07/{RUN_ID}/postings.csv"
    ]
    assert stored == (run_dir / "postings.csv").read_bytes()


def test_republishing_the_same_run_is_idempotent(tmp_path: Path):
    transport = FakeTransport()
    sink = _sink(transport)
    run_dir = _run_dir(tmp_path)
    args = {
        "source": "WORKNET",
        "collected_at": COLLECTED_AT,
        "pipeline_run_id": RUN_ID,
    }

    first = sink.upload_run(run_dir, **args)
    second = sink.upload_run(run_dir, **args)

    assert first.uploaded and not first.unchanged
    assert second.unchanged and not second.uploaded
    assert second.ok


def test_a_reused_run_id_with_different_bytes_is_reported_not_overwritten(
    tmp_path: Path,
):
    """Overwriting would destroy an earlier snapshot that cannot be recollected."""

    transport = FakeTransport()
    sink = _sink(transport)
    args = {
        "source": "WORKNET",
        "collected_at": COLLECTED_AT,
        "pipeline_run_id": RUN_ID,
    }
    sink.upload_run(_run_dir(tmp_path), **args)

    changed = _run_dir(tmp_path, **{"manifest.json": '{"source_site": "OTHER"}\n'})
    result = sink.upload_run(changed, **args)

    assert not result.ok
    assert any("different content" in entry["error"] for entry in result.failed)
    stored = transport.stored[
        f"/gitjob/raw/worknet/dt=2026-09-07/{RUN_ID}/manifest.json"
    ]
    assert b"WORKNET" in stored


def test_a_transport_failure_is_returned_not_raised(tmp_path: Path):
    """The local snapshot is already written; a NameNode hiccup must not raise."""

    transport = FakeTransport(fail_create_for=("postings.csv",))
    result = _sink(transport).upload_run(
        _run_dir(tmp_path),
        source="WORKNET",
        collected_at=COLLECTED_AT,
        pipeline_run_id=RUN_ID,
    )

    assert not result.ok
    assert [entry["file"] for entry in result.failed] == ["postings.csv"]
    # The other two still landed.
    assert len(result.uploaded) == 2


def test_a_missing_local_file_is_reported(tmp_path: Path):
    run_dir = _run_dir(tmp_path)
    (run_dir / "postings.csv").unlink()

    result = _sink(FakeTransport()).upload_run(
        run_dir,
        source="WORKNET",
        collected_at=COLLECTED_AT,
        pipeline_run_id=RUN_ID,
    )
    assert any(entry["error"] == "local file missing" for entry in result.failed)


def test_upload_record_is_written_locally(tmp_path: Path):
    run_dir = _run_dir(tmp_path)
    result = _sink(FakeTransport()).upload_run(
        run_dir,
        source="WORKNET",
        collected_at=COLLECTED_AT,
        pipeline_run_id=RUN_ID,
    )
    path = write_upload_record(run_dir, result)

    recorded = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == RAW_UPLOAD_RECORD
    assert recorded["run_path"].endswith(RUN_ID)
    assert len(recorded["uploaded"]) == len(RUN_FILENAMES)


def test_the_upload_record_is_not_itself_published(tmp_path: Path):
    transport = FakeTransport()
    run_dir = _run_dir(tmp_path)
    sink = _sink(transport)
    args = {
        "source": "WORKNET",
        "collected_at": COLLECTED_AT,
        "pipeline_run_id": RUN_ID,
    }
    write_upload_record(run_dir, sink.upload_run(run_dir, **args))
    sink.upload_run(run_dir, **args)

    assert all(RAW_UPLOAD_RECORD not in path for path in transport.stored)


# --- configuration --------------------------------------------------------


def test_sink_is_absent_without_a_webhdfs_url():
    """A developer with no NameNode gets a local-only run, not a failure."""

    assert sink_from_env({}) is None
    assert sink_from_env({"RAW_ROOT": "hdfs:///gitjob/raw"}) is None


def test_sink_is_built_from_the_compose_environment():
    sink = sink_from_env(
        {
            "WEBHDFS_URL": BASE_URL,
            "WEBHDFS_USER": "hadoop",
            "RAW_ROOT": "hdfs:///gitjob/raw",
        }
    )
    assert sink is not None
    assert sink.client.base_url == BASE_URL
    assert sink.raw_root == "hdfs:///gitjob/raw"


def test_blank_user_falls_back_to_the_documented_default():
    sink = sink_from_env({"WEBHDFS_URL": BASE_URL, "WEBHDFS_USER": "  "})
    assert sink is not None
    assert sink.client.user == "hadoop"


def test_two_sites_land_in_separate_partitions(tmp_path: Path):
    """Aggregation splits denominators by site (S15P21E102-94 §3.5)."""

    transport = FakeTransport()
    sink = _sink(transport)
    for site in ("WORKNET", "SARAMIN"):
        sink.upload_run(
            _run_dir(tmp_path / site),
            source=site,
            collected_at=COLLECTED_AT,
            pipeline_run_id=f"{site}-20260907T001000Z",
        )

    assert any("/raw/worknet/" in path for path in transport.stored)
    assert any("/raw/saramin/" in path for path in transport.stored)


def test_consecutive_days_land_in_separate_partitions(tmp_path: Path):
    transport = FakeTransport()
    sink = _sink(transport)
    for offset in (0, 1):
        moment = COLLECTED_AT + timedelta(days=offset)
        sink.upload_run(
            _run_dir(tmp_path / str(offset)),
            source="WORKNET",
            collected_at=moment,
            pipeline_run_id=f"WORKNET-{offset}",
        )

    assert any("dt=2026-09-07" in path for path in transport.stored)
    assert any("dt=2026-09-08" in path for path in transport.stored)
