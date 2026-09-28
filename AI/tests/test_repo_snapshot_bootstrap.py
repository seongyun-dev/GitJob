import hashlib
import json
import urllib.parse
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from common.webhdfs import WebHdfsClient, WebHdfsResponse, normalize_hdfs_path
from github.client import RateLimitState
from github.contracts import GitHubRepoSnapshotBatch, RepoCollectionPolicy
from github.repo_fetch_orchestrator import (
    RepoActivityCandidate,
    RepoFetchRun,
)
from github.repo_fetch_store import WebHdfsArtifactStore
from github.repo_snapshot_bootstrap import BootstrapBatchRunner


class MemoryWebHdfsTransport:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.pending_path: str | None = None

    def request(
        self,
        method: str,
        url: str,
        *,
        body: Path | bytes | None = None,
        timeout: float,
    ) -> WebHdfsResponse:
        assert timeout > 0
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parsed.query)
        operation = query.get("op", [None])[0]
        path = parsed.path.removeprefix("/webhdfs/v1")
        if parsed.netloc == "datanode":
            assert self.pending_path is not None
            content = body.read_bytes() if isinstance(body, Path) else body
            assert isinstance(content, bytes)
            self.objects[self.pending_path] = content
            return WebHdfsResponse(201, {}, b"")
        if operation == "GETFILESTATUS":
            status = 200 if path in self.objects else 404
            return WebHdfsResponse(status, {}, b"{}")
        if operation == "OPEN":
            if path not in self.objects:
                return WebHdfsResponse(404, {}, b"missing")
            return WebHdfsResponse(200, {}, self.objects[path])
        if operation == "MKDIRS":
            return WebHdfsResponse(200, {}, b'{"boolean":true}')
        if operation == "CREATE":
            self.pending_path = path
            return WebHdfsResponse(
                307,
                {"Location": "http://datanode/upload"},
                b"",
            )
        if operation == "RENAME":
            destination = query["destination"][0]
            self.objects[destination] = self.objects.pop(path)
            return WebHdfsResponse(200, {}, b'{"boolean":true}')
        if operation == "DELETE":
            self.objects.pop(path, None)
            return WebHdfsResponse(200, {}, b'{"boolean":true}')
        raise AssertionError((method, url))


class FakeClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class ScriptedOrchestrator:
    def __init__(self, runs: list[RepoFetchRun]) -> None:
        self.runs = runs
        self.dataset_snapshot_id = runs[0].batch.dataset_snapshot_id
        self.pipeline_run_id = runs[0].batch.pipeline_run_id
        self.progress = None

    def run(self, candidates: object, **kwargs: object) -> RepoFetchRun:
        return self.runs.pop(0)


def candidate() -> RepoActivityCandidate:
    return RepoActivityCandidate(
        repo_id=1,
        repo_name="octo/repo",
        activity_count=10,
        activity_rank=1,
        activity_metric="gh_archive_event_count",
        activity_period_start=date(2026, 8, 1),
        activity_period_end=date(2026, 8, 31),
    )


def run_result(
    *,
    stopped_reason: str | None,
    status: str,
    active_seconds: float,
    reset: int = 105,
) -> RepoFetchRun:
    batch = GitHubRepoSnapshotBatch(
        schema_version="github-repo-snapshot/v1",
        dataset_snapshot_id="snapshot-001",
        pipeline_run_id="run-001",
        collector_version="test/v1",
        generated_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        collection_policy=RepoCollectionPolicy(
            policy_version="test/v1",
            top_n_limit=1,
            max_api_calls=100,
            max_runtime_seconds=100,
            max_tree_entries=100,
            max_artifact_files=10,
            max_artifact_bytes=1000,
        ),
        records=(),
    )
    rate = RateLimitState(5000, 0, 5000, reset, "core")
    return RepoFetchRun(
        batch=batch,
        stopped_reason=stopped_reason,
        rate_limit_before=rate,
        rate_limit_after=rate,
        control_requests=(),
        checkpoint_rows=[
            {
                "repo_id": 1,
                "repo_name": "octo/repo",
                "rank": 1,
                "status": status,
                "api_calls": 3,
                "core_calls": 3,
                "raw_calls": 0,
            }
        ],
        active_runtime_seconds=active_seconds,
    )


def test_webhdfs_artifact_store_is_immutable_and_returns_contract_uri() -> None:
    transport = MemoryWebHdfsTransport()
    store = WebHdfsArtifactStore(
        base_url="http://namenode:9870/webhdfs/v1",
        root=(
            "hdfs:///gitjob/analysis_input/github/repo_snapshot/"
            "snapshot_id=snapshot-001/artifacts"
        ),
        transport=transport,
    )

    uri = store.store(
        policy_version="policy/v1",
        repo_id=1,
        pinned_commit_sha="a" * 40,
        path="package.json",
        content=b"{}",
    )
    assert uri.startswith("hdfs:///gitjob/analysis_input/github/repo_snapshot/")
    assert store.client.read(uri) == b"{}"
    assert (
        store.store(
            policy_version="policy/v1",
            repo_id=1,
            pinned_commit_sha="a" * 40,
            path="package.json",
            content=b"{}",
        )
        == uri
    )
    with pytest.raises(FileExistsError):
        store.store(
            policy_version="policy/v1",
            repo_id=1,
            pinned_commit_sha="a" * 40,
            path="package.json",
            content=b'{"changed":true}',
        )
    with pytest.raises(ValueError, match="traversal"):
        normalize_hdfs_path("/gitjob/analysis_input/../raw")


def test_bootstrap_waits_resumes_and_publishes_with_webhdfs_readback(
    tmp_path: Path,
) -> None:
    clock = FakeClock(100)
    transport = MemoryWebHdfsTransport()
    publisher = WebHdfsClient(
        "http://namenode:9870/webhdfs/v1",
        transport=transport,
    )
    orchestrator = ScriptedOrchestrator(
        [
            run_result(
                stopped_reason="RATE_LIMIT_RESPONSE",
                status="RATE_LIMITED",
                active_seconds=1,
            ),
            run_result(stopped_reason=None, status="NOT_FOUND", active_seconds=2),
        ]
    )
    result = BootstrapBatchRunner(
        orchestrator=orchestrator,  # type: ignore[arg-type]
        candidates=[candidate()],
        output=tmp_path / "snapshot.json",
        summary_output=tmp_path / "summary.json",
        failure_output=tmp_path / "failures.json",
        state_output=tmp_path / "state.json",
        publisher=publisher,
        publish_root=(
            "/gitjob/analysis_input/github/repo_snapshot/snapshot_id=snapshot-001"
        ),
        sleep=clock.sleep,
        epoch=clock,
        monotonic=clock,
    ).run()

    assert result.exit_code == 0
    assert result.summary["cycle_count"] == 2
    assert result.summary["active_runtime_seconds"] == 3
    assert result.summary["rate_limit_wait_seconds"] == 10
    assert result.summary["snapshot_published"] is True
    assert result.published_uris["snapshot"].endswith("/snapshot.json")
    assert result.published_uris["success"].endswith("/_SUCCESS.json")
    assert (
        publisher.read(result.published_uris["snapshot"])
        == (tmp_path / "snapshot.json").read_bytes()
    )
    failures = json.loads((tmp_path / "failures.json").read_text())
    assert failures["repos"][0]["status"] == "NOT_FOUND"
    success = json.loads(publisher.read(result.published_uris["success"]))
    assert set(success["objects"]) == {"snapshot", "summary", "failures"}
    for value in success["objects"].values():
        assert (
            hashlib.sha256(publisher.read(value["uri"])).hexdigest() == value["sha256"]
        )


def test_incomplete_cycle_never_publishes_final_snapshot(tmp_path: Path) -> None:
    orchestrator = ScriptedOrchestrator(
        [
            run_result(
                stopped_reason="API_CALL_BUDGET",
                status="PENDING",
                active_seconds=1,
            )
        ]
    )
    result = BootstrapBatchRunner(
        orchestrator=orchestrator,  # type: ignore[arg-type]
        candidates=[candidate()],
        output=tmp_path / "snapshot.json",
        summary_output=tmp_path / "summary.json",
        failure_output=tmp_path / "failures.json",
        state_output=tmp_path / "state.json",
    ).run()

    assert result.exit_code == 2
    assert not (tmp_path / "snapshot.json").exists()
    assert result.summary["snapshot_published"] is False


def test_progress_state_records_throughput_eta_and_status_counts(
    tmp_path: Path,
) -> None:
    cycle = run_result(
        stopped_reason="API_CALL_BUDGET",
        status="COMPLETE",
        active_seconds=2,
    )
    cycle.checkpoint_rows.append(
        {
            "repo_id": 2,
            "repo_name": "octo/next",
            "rank": 2,
            "status": "PENDING",
            "api_calls": 0,
            "core_calls": 0,
            "raw_calls": 0,
        }
    )
    second = RepoActivityCandidate(
        repo_id=2,
        repo_name="octo/next",
        activity_count=9,
        activity_rank=2,
        activity_metric="gh_archive_event_count",
        activity_period_start=date(2026, 8, 1),
        activity_period_end=date(2026, 8, 31),
    )
    BootstrapBatchRunner(
        orchestrator=ScriptedOrchestrator([cycle]),  # type: ignore[arg-type]
        candidates=[candidate(), second],
        output=tmp_path / "snapshot.json",
        summary_output=tmp_path / "summary.json",
        failure_output=tmp_path / "failures.json",
        state_output=tmp_path / "state.json",
    ).run()

    progress = json.loads((tmp_path / "state.json").read_text())["progress"]
    assert progress["terminal"] == 1
    assert progress["remaining"] == 1
    assert progress["throughput_repos_per_second"] == 0.5
    assert progress["eta_active_seconds"] == 2
    assert progress["status_counts"] == {"COMPLETE": 1, "PENDING": 1}


def test_restart_finishes_persisted_rate_limit_wait(tmp_path: Path) -> None:
    clock = FakeClock(103)
    state_output = tmp_path / "state.json"
    state_output.write_text(
        json.dumps(
            {
                "schema_version": "github-repo-snapshot-bootstrap-summary/v1",
                "dataset_snapshot_id": "snapshot-001",
                "pipeline_run_id": "run-001",
                "cycle_count": 1,
                "control_core_calls": 1,
                "active_runtime_seconds": 1.0,
                "rate_limit_wait_count": 1,
                "rate_limit_wait_seconds": 0.0,
                "rate_limit_wait_started_epoch": 100.0,
                "next_resume_epoch": 110.0,
            }
        ),
        encoding="utf-8",
    )
    result = BootstrapBatchRunner(
        orchestrator=ScriptedOrchestrator(
            [run_result(stopped_reason=None, status="NOT_FOUND", active_seconds=2)]
        ),  # type: ignore[arg-type]
        candidates=[candidate()],
        output=tmp_path / "snapshot.json",
        summary_output=tmp_path / "summary.json",
        failure_output=tmp_path / "failures.json",
        state_output=state_output,
        sleep=clock.sleep,
        epoch=clock,
        monotonic=clock,
    ).run()

    assert clock.value == 110
    assert result.summary["rate_limit_wait_seconds"] == 10
    persisted = json.loads(state_output.read_text())
    assert persisted["next_resume_epoch"] is None
    assert persisted["rate_limit_wait_started_epoch"] is None
