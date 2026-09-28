"""A→C `analysis_input` publication for collector runs (S15P21E102-220).

No network: every case drives a recording fake transport, following
`test_job_raw_sink.py`. The fake is restated rather than imported because that
is how the suite already shares it (`test_job_raw_sink.py` says the same about
`test_gharchive_webhdfs_sink.py`), and importing across test modules would make
one suite's refactor break another's collection.
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from common.webhdfs import WebHdfsClient, WebHdfsResponse
from job.collector.analysis_input import (
    ANALYSIS_INPUT_PUBLISH_RECORD,
    DEFAULT_ANALYSIS_INPUT_ROOT,
    AnalysisInputPublishResult,
    JobPostingAnalysisInputPublisher,
    analysis_input_run_path,
    publisher_from_env,
    release_blockers,
    write_publish_record,
)
from job.collector.raw_sink import RUN_FILENAMES
from job.jobkorea_contract import JOBKOREA_V3_DUTY_ROLE_PAIRS

BASE_URL = "http://hdfs-namenode:9870/webhdfs/v1"
DATANODE = "http://hdfs-datanode:9864/upload"
SOURCE = "SARAMIN"
RUN_ID = "SARAMIN-20260911T001000Z"


def _boolean(value: bool) -> bytes:
    return json.dumps({"boolean": value}).encode()


@dataclass
class FakeTransport:
    """An in-memory WebHDFS mirroring the real two-step CREATE."""

    stored: dict[str, bytes] = field(default_factory=dict)
    fail_create_for: tuple[str, ...] = ()
    # Bytes to hand back from OPEN regardless of what was stored, so a
    # corrupted read-back can be exercised without corrupting the store.
    read_override: dict[str, bytes] = field(default_factory=dict)
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
                return WebHdfsResponse(200, {}, b'{"FileStatus":{"length":0}}')
            return WebHdfsResponse(404, {}, b'{"RemoteException":{}}')
        if operation == "MKDIRS":
            return WebHdfsResponse(200, {}, _boolean(True))
        if operation == "OPEN":
            if path in self.read_override:
                return WebHdfsResponse(200, {}, self.read_override[path])
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
            content = self.stored.pop(path, None)
            if content is None:
                return WebHdfsResponse(200, {}, _boolean(False))
            self.stored[destination] = content
            return WebHdfsResponse(200, {}, _boolean(True))
        if operation == "DELETE":
            self.stored.pop(path, None)
            return WebHdfsResponse(200, {}, _boolean(True))
        raise AssertionError(f"unexpected WebHDFS operation: {operation}")


def _client(transport: FakeTransport) -> WebHdfsClient:
    return WebHdfsClient(base_url=BASE_URL, transport=transport)


def _run_dir(
    tmp_path: Path,
    *,
    records: int = 3,
    detail_errors: int = 0,
    invalid_records: int = 0,
    stopped_reason: str | None = None,
    bind_batch: bool = True,
    batch_body: str = "batch",
    source_site: str = SOURCE,
    pipeline_run_id: str = RUN_ID,
) -> Path:
    """A local run directory shaped like what the four collectors write."""

    run_dir = tmp_path / "saramin" / RUN_ID
    run_dir.mkdir(parents=True)
    batch = json.dumps({"records": batch_body}, ensure_ascii=False).encode()
    (run_dir / "job_analysis_input.json").write_bytes(batch)
    (run_dir / "postings.csv").write_text("id,title\n1,backend\n", encoding="utf-8")

    manifest: dict[str, object] = {
        "schema_version": "job-analysis-input/v1",
        "source_site": source_site,
        "collector_version": "saramin/1.4.0",
        "pipeline_run_id": pipeline_run_id,
        "dataset_snapshot_id": "ds_saramin_20260911",
        "collected_at": "2026-09-11T00:10:00+00:00",
        "counts": {
            "records": records,
            "detail_errors": detail_errors,
            "invalid_records": invalid_records,
        },
        "stopped_reason": stopped_reason,
        "outputs": {"job_analysis_input.json": "job_analysis_input.json"},
    }
    if bind_batch:
        manifest["output_sha256"] = {
            "job_analysis_input.json": hashlib.sha256(batch).hexdigest()
        }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return run_dir


def _publish(run_dir: Path, transport: FakeTransport) -> AnalysisInputPublishResult:
    publisher = JobPostingAnalysisInputPublisher(client=_client(transport))
    return publisher.publish_run(run_dir, source=SOURCE, pipeline_run_id=RUN_ID)


def test_run_path_has_no_date_partition():
    path = analysis_input_run_path(source=SOURCE, pipeline_run_id=RUN_ID)
    assert path.as_posix() == f"/gitjob/analysis_input/jobs/saramin/{RUN_ID}"
    assert "dt=" not in path.as_posix()


@pytest.mark.parametrize(
    "source, run_id",
    [
        ("saramin/../raw", RUN_ID),
        ("saramin", "../../raw/escape"),
        ("", RUN_ID),
        ("saramin", ".."),
    ],
)
def test_run_path_refuses_traversal(source, run_id):
    with pytest.raises(ValueError):
        analysis_input_run_path(source=source, pipeline_run_id=run_id)


def test_publish_stores_every_file_and_reads_it_back(tmp_path):
    transport = FakeTransport()
    result = _publish(_run_dir(tmp_path), transport)

    assert result.ok and not result.skipped
    prefix = f"/gitjob/analysis_input/jobs/saramin/{RUN_ID}"
    assert result.run_path == prefix
    assert set(transport.stored) == {f"{prefix}/{name}" for name in RUN_FILENAMES}
    assert len(result.published) == 3
    assert result.unchanged == ()
    assert len(result.read_back) == 3


def test_manifest_is_published_last(tmp_path):
    """A reader that sees the manifest must find the batch already there."""

    transport = FakeTransport()
    _publish(_run_dir(tmp_path), transport)

    renames = [
        urllib.parse.unquote(url.rsplit("destination=", 1)[1].split("&", 1)[0])
        for method, url in transport.calls
        if method == "PUT" and "op=RENAME" in url
    ]
    assert [Path(path).name for path in renames] == list(RUN_FILENAMES)
    assert renames[-1].endswith("manifest.json")


def test_republishing_identical_content_is_unchanged(tmp_path):
    transport = FakeTransport()
    run_dir = _run_dir(tmp_path)
    first = _publish(run_dir, transport)
    stored_after_first = dict(transport.stored)

    second = _publish(run_dir, transport)

    assert first.ok and second.ok
    assert len(second.unchanged) == 3
    assert second.published == ()
    # Nothing moved: the same run id with the same bytes is a no-op.
    assert transport.stored == stored_after_first


def test_same_run_id_with_different_content_is_refused(tmp_path):
    transport = FakeTransport()
    _publish(_run_dir(tmp_path), transport)
    published = dict(transport.stored)

    replacement = _run_dir(tmp_path / "second", batch_body="different")
    result = _publish(replacement, transport)

    assert not result.ok
    assert any(
        entry["error"] == "object exists with different content"
        for entry in result.failed
    )
    # The earlier publication survives untouched.
    assert transport.stored == published


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"stopped_reason": "page_limit"}, "COLLECTOR_STOPPED_EARLY"),
        ({"detail_errors": 2}, "DETAIL_COLLECTION_FAILED"),
        ({"invalid_records": 1}, "INVALID_SOURCE_RECORDS"),
        ({"records": 0}, "EMPTY_RUN"),
        ({"bind_batch": False}, "UNBOUND_LEGACY_MANIFEST"),
        ({"source_site": "WORKNET"}, "IDENTITY_MISMATCH"),
        ({"pipeline_run_id": "OTHER-RUN"}, "IDENTITY_MISMATCH"),
    ],
)
def test_incomplete_runs_are_not_published(tmp_path, kwargs, expected):
    transport = FakeTransport()
    result = _publish(_run_dir(tmp_path, **kwargs), transport)

    assert result.skipped and not result.ok
    assert expected in result.blockers
    # Refused before any byte moved.
    assert transport.stored == {}
    assert result.published == () and result.unchanged == ()


def test_manifest_that_does_not_bind_the_batch_bytes_is_refused(tmp_path):
    run_dir = _run_dir(tmp_path)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["output_sha256"]["job_analysis_input.json"] = "0" * 64
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )

    transport = FakeTransport()
    result = _publish(run_dir, transport)

    assert "BATCH_CHECKSUM_MISMATCH" in result.blockers
    assert transport.stored == {}


@pytest.mark.parametrize("missing", RUN_FILENAMES)
def test_a_missing_file_blocks_the_run(tmp_path, missing):
    run_dir = _run_dir(tmp_path)
    (run_dir / missing).unlink()

    transport = FakeTransport()
    result = _publish(run_dir, transport)

    assert f"MISSING_FILE:{missing}" in result.blockers
    assert transport.stored == {}


def test_unreadable_manifest_blocks_the_run(tmp_path):
    run_dir = _run_dir(tmp_path)
    (run_dir / "manifest.json").write_text("not json", encoding="utf-8")

    result = _publish(run_dir, FakeTransport())

    assert result.blockers == ("MANIFEST_UNREADABLE",)


def test_read_back_mismatch_is_reported(tmp_path):
    """A store that accepts bytes and returns different ones must not pass."""

    transport = FakeTransport()
    run_dir = _run_dir(tmp_path)
    transport.read_override[
        f"/gitjob/analysis_input/jobs/saramin/{RUN_ID}/postings.csv"
    ] = b"corrupted"

    result = _publish(run_dir, transport)

    assert not result.ok
    assert result.failed == (
        {"file": "postings.csv", "error": "read-back content mismatch"},
    )
    assert len(result.read_back) == 2


def test_upload_failure_is_returned_not_raised(tmp_path):
    transport = FakeTransport(fail_create_for=("postings.csv",))

    result = _publish(_run_dir(tmp_path), transport)

    assert not result.ok
    assert [entry["file"] for entry in result.failed] == ["postings.csv"]
    # Read-back is not attempted for a run that did not fully upload.
    assert result.read_back == ()


def test_release_blockers_accepts_a_complete_run(tmp_path):
    assert (
        release_blockers(_run_dir(tmp_path), source=SOURCE, pipeline_run_id=RUN_ID)
        == ()
    )


def _as_jobkorea_v3_active(run_dir: Path, *, body_status: str = "BLOCKED") -> None:
    batch_path = run_dir / "job_analysis_input.json"
    batch = json.dumps({"records": [{"body_status": body_status}]}).encode()
    batch_path.write_bytes(batch)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        source_site="JOBKOREA",
        collector_version="jobkorea-crawler/v3",
        counts={"records": 1, "detail_errors": 1, "invalid_records": 0},
        stats={"scan_stop_reason": "all_scopes_complete"},
        source={
            "site": "JOBKOREA",
            "mode": "active_listing",
            "duty_scopes": [
                {
                    "code": code,
                    "name": f"duty-{code}",
                    "target_role": role,
                    "scan_stop_reason": "short_page",
                }
                for code, role in sorted(JOBKOREA_V3_DUTY_ROLE_PAIRS)
            ],
        },
        output_sha256={"job_analysis_input.json": hashlib.sha256(batch).hexdigest()},
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def test_jobkorea_v3_record_local_detail_failures_can_be_published(tmp_path):
    run_dir = _run_dir(
        tmp_path,
        records=1,
        detail_errors=1,
        source_site="JOBKOREA",
    )
    _as_jobkorea_v3_active(run_dir)

    assert release_blockers(run_dir, source="JOBKOREA", pipeline_run_id=RUN_ID) == ()


def test_jobkorea_v3_detail_failures_must_remain_in_the_bound_batch(tmp_path):
    run_dir = _run_dir(
        tmp_path,
        records=1,
        detail_errors=1,
        source_site="JOBKOREA",
    )
    _as_jobkorea_v3_active(run_dir, body_status="TEXT_AVAILABLE")

    assert "DETAIL_COLLECTION_FAILED" in release_blockers(
        run_dir, source="JOBKOREA", pipeline_run_id=RUN_ID
    )


def test_jobkorea_v3_full_snapshot_must_finish_every_scope(tmp_path):
    run_dir = _run_dir(
        tmp_path,
        records=1,
        detail_errors=1,
        source_site="JOBKOREA",
    )
    _as_jobkorea_v3_active(run_dir)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source"]["duty_scopes"][0]["scan_stop_reason"] = "max_pages"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert "COLLECTOR_STOPPED_EARLY" in release_blockers(
        run_dir, source="JOBKOREA", pipeline_run_id=RUN_ID
    )


# --- S15P21E102-370: reconciled detail errors are publishable for any source ---
#
# 상세 조회 직전에 공고가 내려가면 목록에는 있고 상세는 404 다. 수집기는 그 공고를
# 버리지 않고 BLOCKED 레코드로 보존하므로 데이터 누락이 없다. 그런데 게이트가 이
# reconciliation 을 JobKorea v3 active_listing 에서만 인정해, 같은 방식으로 보존한
# Saramin run 이 DETAIL_COLLECTION_FAILED 로 막혔다.
#
# 통과 조건은 출처가 아니라 **보존 여부**다. 신고한 실패 수가 bound batch 에 남은
# BLOCKED 레코드 수와 같고, manifest 가 세는 레코드 수가 batch 실물과 같아야 한다.


def _as_reconciled_detail_errors(
    run_dir: Path, *, records: int, blocked: int, declared_errors: int | None = None
) -> None:
    """Rewrite the run so `records` rows exist and `blocked` of them are BLOCKED."""

    rows = [
        {"body_status": "BLOCKED" if index < blocked else "TEXT_AVAILABLE"}
        for index in range(records)
    ]
    batch = json.dumps({"records": rows}, ensure_ascii=False).encode()
    (run_dir / "job_analysis_input.json").write_bytes(batch)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    counts = dict(manifest["counts"])
    counts["records"] = records
    counts["detail_errors"] = blocked if declared_errors is None else declared_errors
    manifest["counts"] = counts
    manifest["output_sha256"] = {
        "job_analysis_input.json": hashlib.sha256(batch).hexdigest()
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def test_saramin_reconciled_detail_errors_can_be_published(tmp_path):
    """The production shape of SARAMIN-20260921T055545Z: 1 error, 1 BLOCKED row."""

    run_dir = _run_dir(tmp_path, records=3, detail_errors=1)
    _as_reconciled_detail_errors(run_dir, records=3, blocked=1)

    assert release_blockers(run_dir, source=SOURCE, pipeline_run_id=RUN_ID) == ()


def test_saramin_detail_errors_without_a_blocked_record_are_refused(tmp_path):
    """A producer must not report failures while dropping the postings."""

    run_dir = _run_dir(tmp_path, records=3, detail_errors=1)
    _as_reconciled_detail_errors(run_dir, records=3, blocked=0, declared_errors=1)

    assert "DETAIL_COLLECTION_FAILED" in release_blockers(
        run_dir, source=SOURCE, pipeline_run_id=RUN_ID
    )


def test_saramin_detail_errors_must_equal_the_blocked_count(tmp_path):
    """Partially preserved failures are still unexplained losses."""

    run_dir = _run_dir(tmp_path, records=3, detail_errors=2)
    _as_reconciled_detail_errors(run_dir, records=3, blocked=1, declared_errors=2)

    assert "DETAIL_COLLECTION_FAILED" in release_blockers(
        run_dir, source=SOURCE, pipeline_run_id=RUN_ID
    )


def test_saramin_reconciliation_requires_the_manifest_record_count_to_match(tmp_path):
    """Counting rows the batch does not carry hides a drop behind a matching pair."""

    run_dir = _run_dir(tmp_path, records=3, detail_errors=1)
    _as_reconciled_detail_errors(run_dir, records=3, blocked=1)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["counts"]["records"] = 4
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert "DETAIL_COLLECTION_FAILED" in release_blockers(
        run_dir, source=SOURCE, pipeline_run_id=RUN_ID
    )


def test_reconciled_detail_errors_do_not_excuse_invalid_records(tmp_path):
    run_dir = _run_dir(tmp_path, records=3, detail_errors=1, invalid_records=1)
    _as_reconciled_detail_errors(run_dir, records=3, blocked=1)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["counts"]["invalid_records"] = 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert "INVALID_SOURCE_RECORDS" in release_blockers(
        run_dir, source=SOURCE, pipeline_run_id=RUN_ID
    )


def test_reconciled_detail_errors_do_not_excuse_an_early_stop(tmp_path):
    run_dir = _run_dir(
        tmp_path, records=3, detail_errors=1, stopped_reason="RATE_LIMITED"
    )
    _as_reconciled_detail_errors(run_dir, records=3, blocked=1)

    assert "COLLECTOR_STOPPED_EARLY" in release_blockers(
        run_dir, source=SOURCE, pipeline_run_id=RUN_ID
    )


def test_reconciled_detail_errors_do_not_excuse_an_unverified_batch(tmp_path):
    """Reconciliation reads the batch, so an unbound batch must still be refused."""

    run_dir = _run_dir(tmp_path, records=3, detail_errors=1)
    _as_reconciled_detail_errors(run_dir, records=3, blocked=1)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_sha256"] = {"job_analysis_input.json": "0" * 64}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert "BATCH_CHECKSUM_MISMATCH" in release_blockers(
        run_dir, source=SOURCE, pipeline_run_id=RUN_ID
    )


def test_publisher_from_env_requires_webhdfs():
    assert publisher_from_env({}) is None
    assert publisher_from_env({"WEBHDFS_URL": "   "}) is None

    publisher = publisher_from_env({"WEBHDFS_URL": BASE_URL})
    assert publisher is not None
    assert publisher.root == DEFAULT_ANALYSIS_INPUT_ROOT

    overridden = publisher_from_env(
        {"WEBHDFS_URL": BASE_URL, "ANALYSIS_INPUT_JOBS_ROOT": "hdfs:///other/jobs"}
    )
    assert overridden is not None
    assert overridden.root == "hdfs:///other/jobs"


def test_publish_record_is_written_locally_and_not_uploaded(tmp_path):
    transport = FakeTransport()
    run_dir = _run_dir(tmp_path)
    result = _publish(run_dir, transport)

    path = write_publish_record(run_dir, result)

    assert path.name == ANALYSIS_INPUT_PUBLISH_RECORD
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["run_path"] == result.run_path
    assert record["blockers"] == []
    assert len(record["read_back"]) == 3
    assert not any(
        ANALYSIS_INPUT_PUBLISH_RECORD in stored for stored in transport.stored
    )
