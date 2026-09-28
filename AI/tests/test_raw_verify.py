"""Verifying that archived runs are still in HDFS Raw.

The case this module exists for is `test_a_claimed_file_that_vanished_is_caught`
— on 2026-09-08 the HDFS volumes were recreated and 5,124 Worknet postings plus
GH Archive's 744-file bootstrap disappeared while every local record still said
they were archived. `hdfs fsck` reported HEALTHY.

The other half of the cases is about not crying wolf. A check that reports the
twelve never-archived development runs as failures every time is a check nobody
reads (S15P21E102-186), so `NEVER_UPLOADED` is reported and not alerted.

No network: the WebHDFS client is a recording double.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from common.webhdfs import WebHdfsError
from job.collector.raw_verify import (
    STATE_ERROR,
    STATE_MISSING,
    STATE_NEVER_UPLOADED,
    STATE_OK,
    STATE_SIZE_MISMATCH,
    STATE_UPLOAD_FAILED,
    verify_output_root,
    verify_run,
    verify_sites,
)

RUN = "WORKNET-20260908T003203Z"
BASE = f"hdfs:///gitjob/raw/worknet/dt=2026-09-08/{RUN}"
FILENAMES = ("job_analysis_input.json", "postings.csv", "manifest.json")


@dataclass
class FakeClient:
    """Answers `length` from a dict, and records what was asked."""

    lengths: dict[str, int | None] = field(default_factory=dict)
    error: str | None = None
    asked: list[str] = field(default_factory=list)

    def length(self, path) -> int | None:
        key = str(path)
        self.asked.append(key)
        if self.error:
            raise WebHdfsError(self.error)
        return self.lengths.get(key)


def _write_run(
    root: Path,
    *,
    filenames=FILENAMES,
    uploaded: list[str] | None = None,
    unchanged: list[str] | None = None,
    failed: list[dict] | None = None,
    upload_record: bool = True,
    sizes: dict[str, int] | None = None,
) -> Path:
    run_dir = root / RUN
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in filenames:
        size = (sizes or {}).get(name, 10)
        (run_dir / name).write_bytes(b"x" * size)
    if upload_record:
        (run_dir / "raw_upload.json").write_text(
            json.dumps(
                {
                    "run_path": BASE.replace("hdfs://", ""),
                    "uploaded": uploaded if uploaded is not None else [],
                    "unchanged": unchanged if unchanged is not None else [],
                    "failed": failed or [],
                    "recorded_at": "2026-09-08T03:15:34.701517+00:00",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return run_dir


def _all_uris() -> list[str]:
    return [f"{BASE}/{name}" for name in FILENAMES]


def _present(sizes: dict[str, int] | None = None) -> dict[str, int | None]:
    return {
        f"/gitjob/raw/worknet/dt=2026-09-08/{RUN}/{name}": (sizes or {}).get(name, 10)
        for name in FILENAMES
    }


# --- the failure this exists for --------------------------------------------


def test_a_claimed_file_that_vanished_is_caught(tmp_path: Path):
    """The 2026-09-08 loss, reproduced.

    `raw_upload.json` says three files reached Raw and one is gone. The run
    directory looks perfectly healthy locally, which is why nothing noticed
    for a day.
    """

    run_dir = _write_run(tmp_path, uploaded=_all_uris())
    lengths = _present()
    del lengths[f"/gitjob/raw/worknet/dt=2026-09-08/{RUN}/postings.csv"]

    result = verify_run(FakeClient(lengths=lengths), run_dir)

    assert result.state == STATE_MISSING
    assert result.files_claimed == 3
    assert result.files_present == 2
    assert any("postings.csv" in problem for problem in result.problems)
    assert not result.ok


def test_unchanged_counts_as_claimed(tmp_path: Path):
    """`unchanged` is exactly the state that turned out to be untrue.

    The Worknet backfill's record listed all three files as `unchanged` —
    "already there when we looked" — and they were gone five hours later. A
    verifier that only checked `uploaded` would have passed it.
    """

    run_dir = _write_run(tmp_path, unchanged=_all_uris())

    result = verify_run(FakeClient(lengths={}), run_dir)

    assert result.state == STATE_MISSING
    assert result.files_claimed == 3
    assert result.files_present == 0


def test_all_present_is_ok(tmp_path: Path):
    run_dir = _write_run(tmp_path, uploaded=_all_uris())

    result = verify_run(FakeClient(lengths=_present()), run_dir)

    assert result.state == STATE_OK
    assert result.ok
    assert result.files_present == 3


# --- truncation -------------------------------------------------------------


def test_a_shorter_object_is_a_size_mismatch(tmp_path: Path):
    """Existence alone would pass a truncated upload."""

    run_dir = _write_run(tmp_path, uploaded=_all_uris(), sizes={"postings.csv": 100})
    lengths = _present()
    lengths[f"/gitjob/raw/worknet/dt=2026-09-08/{RUN}/postings.csv"] = 40

    result = verify_run(FakeClient(lengths=lengths), run_dir)

    assert result.state == STATE_SIZE_MISMATCH
    assert any("크기 불일치" in problem for problem in result.problems)


def test_a_missing_local_file_does_not_fake_a_mismatch(tmp_path: Path):
    """A local snapshot may be cleaned up; that is not an HDFS problem.

    The archive is the system of record, so once it is verified present the
    local copy is free to go.
    """

    run_dir = _write_run(tmp_path, uploaded=_all_uris())
    (run_dir / "postings.csv").unlink()

    result = verify_run(FakeClient(lengths=_present()), run_dir)

    assert result.state == STATE_OK


# --- not crying wolf --------------------------------------------------------


def test_a_run_with_no_upload_record_is_never_uploaded(tmp_path: Path):
    """Twelve Worknet development runs are permanently in this state.

    Reported so it is visible, and kept out of `problems` so the check does
    not go red forever — the failure mode S15P21E102-186 removed.
    """

    run_dir = _write_run(tmp_path, upload_record=False)

    result = verify_run(FakeClient(), run_dir)

    assert result.state == STATE_NEVER_UPLOADED
    assert result.files_claimed == 0


def test_an_empty_claim_is_never_uploaded_not_ok(tmp_path: Path):
    """A record claiming nothing must not read as a verified archive."""

    run_dir = _write_run(tmp_path, uploaded=[], unchanged=[])

    result = verify_run(FakeClient(), run_dir)

    assert result.state == STATE_NEVER_UPLOADED


def test_never_uploaded_does_not_make_the_summary_red(tmp_path: Path):
    _write_run(tmp_path / "worknet", upload_record=False)

    summary = verify_sites(FakeClient(), tmp_path, ["worknet"])

    assert summary.ok
    assert len(summary.never_uploaded) == 1
    assert summary.problems == ()


def test_a_run_that_already_knew_it_failed_is_reported_separately(tmp_path: Path):
    """The run's own record said so; this is not a new fact."""

    run_dir = _write_run(
        tmp_path,
        uploaded=[],
        failed=[{"file": "postings.csv", "error": "boom"}],
    )

    result = verify_run(FakeClient(), run_dir)

    assert result.state == STATE_UPLOAD_FAILED
    assert not result.ok


# --- robustness -------------------------------------------------------------


def test_a_broker_error_is_reported_not_raised(tmp_path: Path):
    """A NameNode hiccup must not look like data loss.

    Reporting it as `MISSING` would send someone hunting for deleted files.
    """

    run_dir = _write_run(tmp_path, uploaded=_all_uris())

    result = verify_run(FakeClient(error="NameNode unreachable"), run_dir)

    assert result.state == STATE_ERROR
    assert result.detail is not None
    assert "NameNode" in result.detail


def test_an_unreadable_upload_record_is_never_uploaded(tmp_path: Path):
    run_dir = _write_run(tmp_path, uploaded=_all_uris())
    (run_dir / "raw_upload.json").write_text("{ truncated", encoding="utf-8")

    result = verify_run(FakeClient(lengths=_present()), run_dir)

    assert result.state == STATE_NEVER_UPLOADED


def test_the_claimed_uri_is_used_not_a_recomputed_path(tmp_path: Path):
    """Rebuilding the path from `raw_run_path` would hide a disagreement.

    The whole point is to check what the run said it wrote.
    """

    odd = "hdfs:///gitjob/raw/worknet/dt=2026-01-01/OTHER/manifest.json"
    run_dir = _write_run(tmp_path, uploaded=[odd])
    client = FakeClient(lengths={})

    verify_run(client, run_dir)

    assert client.asked == ["/gitjob/raw/worknet/dt=2026-01-01/OTHER/manifest.json"]


# --- walking a collector's output directory ---------------------------------


def test_runs_are_checked_in_name_order(tmp_path: Path):
    for name in ("WORKNET-20260909T000000Z", "WORKNET-20260907T000000Z"):
        (tmp_path / name).mkdir(parents=True)

    results = verify_output_root(FakeClient(), tmp_path)

    assert [item.run for item in results] == [
        "WORKNET-20260907T000000Z",
        "WORKNET-20260909T000000Z",
    ]


def test_a_missing_output_directory_is_not_an_error(tmp_path: Path):
    assert verify_output_root(FakeClient(), tmp_path / "absent") == []


def test_the_summary_counts_each_state(tmp_path: Path):
    root = tmp_path / "worknet"
    _write_run(root, uploaded=_all_uris())
    (root / "WORKNET-20260907T000000Z").mkdir(parents=True)

    summary = verify_sites(FakeClient(lengths=_present()), tmp_path, ["worknet"])
    body = summary.as_dict()

    assert body["checked"] == 2
    assert body["ok"] == 1
    assert body["never_uploaded"] == 1
    assert body["problems"] == []
