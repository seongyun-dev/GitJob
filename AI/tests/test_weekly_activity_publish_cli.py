"""The publisher's operational entry point (S15P21E102-227).

No HDFS and no broker. The CLI is thin on purpose, so what is asserted here is
the part that is its own: reading the Spark summary, refusing a summary that
belongs to another snapshot, the dry run writing nothing, and the exit codes.
The publishing itself is `test_weekly_activity_publish.py`'s subject and is not
re-asserted.
"""

from __future__ import annotations

import json

import pytest
from github import weekly_activity_publish_cli as cli
from github.weekly_activity_publish import WeeklyPublishError

SNAPSHOT = "s15p21e102-224-stream-20260912"
MONDAY = "2026-08-31"
NEXT_MONDAY = "2026-09-07"
PERIOD_ROOT = "hdfs:///gitjob/parquet/github/repo_activity_weekly/period=2026-09"
ROOT = f"{PERIOD_ROOT}/snapshot={SNAPSHOT}"
DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64


def summary(weeks=None, snapshot_id=SNAPSHOT):
    weeks = weeks or {MONDAY: DIGEST}
    root = f"{PERIOD_ROOT}/snapshot={snapshot_id}"
    return {
        "input": {"format": "stream-parquet"},
        "output": {
            "weeks_written": {
                week: {
                    "uri": f"{root}/week={week}",
                    "row_count": 3,
                    "row_digest": digest,
                    "event_count": 9,
                }
                for week, digest in weeks.items()
            }
        },
    }


def write_summary(tmp_path, payload):
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --- reading the summary ---------------------------------------------------


def test_a_missing_summary_file_is_refused(tmp_path):
    with pytest.raises(SystemExit, match="not found"):
        cli.main(
            [
                "--summary",
                str(tmp_path / "nope.json"),
                "--dataset-snapshot-id",
                SNAPSHOT,
                "--dry-run",
            ]
        )


def test_a_summary_that_is_not_json_is_refused(tmp_path):
    path = tmp_path / "summary.json"
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(SystemExit, match="not valid JSON"):
        cli.main(
            ["--summary", str(path), "--dataset-snapshot-id", SNAPSHOT, "--dry-run"]
        )


def test_a_summary_without_written_weeks_is_refused(tmp_path):
    path = write_summary(tmp_path, {"output": {}})

    with pytest.raises(SystemExit, match="published weeks"):
        cli.main(
            ["--summary", str(path), "--dataset-snapshot-id", SNAPSHOT, "--dry-run"]
        )


def test_an_oversized_summary_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "MAX_SUMMARY_BYTES", 10)
    path = write_summary(tmp_path, summary())

    with pytest.raises(SystemExit, match="larger than"):
        cli.main(
            ["--summary", str(path), "--dataset-snapshot-id", SNAPSHOT, "--dry-run"]
        )


# --- the snapshot id has to be the one in the path -------------------------


def test_a_summary_from_another_snapshot_is_refused(tmp_path):
    """The manifest would otherwise name a snapshot the directory is not in."""

    path = write_summary(tmp_path, summary(snapshot_id="some-other-run"))

    with pytest.raises(SystemExit, match="belongs to another snapshot"):
        cli.main(
            ["--summary", str(path), "--dataset-snapshot-id", SNAPSHOT, "--dry-run"]
        )


def test_a_snapshot_id_that_is_only_a_prefix_is_refused(tmp_path):
    path = write_summary(tmp_path, summary())

    with pytest.raises(SystemExit, match="belongs to another snapshot"):
        cli.main(
            [
                "--summary",
                str(path),
                "--dataset-snapshot-id",
                "s15p21e102-224",
                "--dry-run",
            ]
        )


# --- dry run ---------------------------------------------------------------


def test_dry_run_prints_every_week_and_writes_nothing(tmp_path, capsys, monkeypatch):
    def fail(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("dry run must not build clients")

    monkeypatch.setattr(cli, "WebHdfsClient", fail)
    monkeypatch.setattr(cli, "transport_from_env", fail)
    monkeypatch.setattr(cli, "publish_weekly_snapshot", fail)
    path = write_summary(tmp_path, summary({MONDAY: DIGEST, NEXT_MONDAY: OTHER_DIGEST}))

    assert (
        cli.main(
            ["--summary", str(path), "--dataset-snapshot-id", SNAPSHOT, "--dry-run"]
        )
        == 0
    )

    body = json.loads(capsys.readouterr().out)
    assert body["dry_run"] is True
    assert [week["week_start"] for week in body["weeks"]] == [MONDAY, NEXT_MONDAY]
    assert body["weeks"][0]["manifest_uri"] == f"{ROOT}/week={MONDAY}/_SUCCESS.json"
    assert body["weeks"][0]["manifest"]["row_digest"]["value"] == DIGEST


def test_dry_run_needs_no_webhdfs_url(tmp_path, monkeypatch):
    monkeypatch.delenv("WEBHDFS_URL", raising=False)
    path = write_summary(tmp_path, summary())

    assert (
        cli.main(
            ["--summary", str(path), "--dataset-snapshot-id", SNAPSHOT, "--dry-run"]
        )
        == 0
    )


def test_a_real_run_without_a_webhdfs_url_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("WEBHDFS_URL", raising=False)
    path = write_summary(tmp_path, summary())

    with pytest.raises(SystemExit):
        cli.main(["--summary", str(path), "--dataset-snapshot-id", SNAPSHOT])


# --- the real run delegates, and reports ------------------------------------


class _Recorder:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def __call__(self, dataset_snapshot_id, weeks, *, publisher, transport):
        self.calls.append((dataset_snapshot_id, tuple(weeks), transport))
        if self.error is not None:
            raise self.error
        return self.result


class _FakeResult:
    def as_dict(self):
        return {"manifest_uris": {MONDAY: "hdfs:///x/_SUCCESS.json"}}


class _FakeTransport:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_a_real_run_hands_the_weeks_to_the_publisher(tmp_path, capsys, monkeypatch):
    recorder = _Recorder(result=_FakeResult())
    transport = _FakeTransport()
    monkeypatch.setattr(cli, "WebHdfsClient", lambda *a, **k: object())
    monkeypatch.setattr(cli, "transport_from_env", lambda **k: transport)
    monkeypatch.setattr(cli, "publish_weekly_snapshot", recorder)
    path = write_summary(tmp_path, summary())

    exit_code = cli.main(
        [
            "--summary",
            str(path),
            "--dataset-snapshot-id",
            SNAPSHOT,
            "--webhdfs-url",
            "http://hdfs-namenode:9870/webhdfs/v1",
        ]
    )

    assert exit_code == 0
    snapshot_id, weeks, passed_transport = recorder.calls[0]
    assert snapshot_id == SNAPSHOT
    assert [week.week_start for week in weeks] == [MONDAY]
    assert weeks[0].row_digest == DIGEST
    assert passed_transport is transport
    assert transport.closed is True
    body = json.loads(capsys.readouterr().out)
    assert body["broker_configured"] is True
    assert body["dataset_snapshot_id"] == SNAPSHOT


def test_a_publish_failure_exits_non_zero(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "WebHdfsClient", lambda *a, **k: object())
    monkeypatch.setattr(cli, "transport_from_env", lambda **k: None)
    monkeypatch.setattr(
        cli,
        "publish_weekly_snapshot",
        _Recorder(error=WeeklyPublishError("already published with different content")),
    )
    path = write_summary(tmp_path, summary())

    exit_code = cli.main(
        [
            "--summary",
            str(path),
            "--dataset-snapshot-id",
            SNAPSHOT,
            "--webhdfs-url",
            "http://hdfs-namenode:9870/webhdfs/v1",
        ]
    )

    assert exit_code == 1
    assert "different content" in capsys.readouterr().err


def test_a_missing_broker_is_reported_not_failed(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "WebHdfsClient", lambda *a, **k: object())
    monkeypatch.setattr(cli, "transport_from_env", lambda **k: None)
    monkeypatch.setattr(cli, "publish_weekly_snapshot", _Recorder(result=_FakeResult()))
    path = write_summary(tmp_path, summary())

    exit_code = cli.main(
        [
            "--summary",
            str(path),
            "--dataset-snapshot-id",
            SNAPSHOT,
            "--webhdfs-url",
            "http://hdfs-namenode:9870/webhdfs/v1",
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["broker_configured"] is False


# --- the contract this module must not restate -----------------------------


def test_the_cli_does_not_reimplement_the_publisher():
    """`-227`'s whole point: one publisher, one place.

    Reads identifiers out of the AST rather than grepping the text, so the
    module can still *explain* in prose what it delegates.
    """

    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(cli.__file__).read_text(encoding="utf-8"))
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    for forbidden in ("store_immutable", "completion_envelope", "EventEnvelope"):
        assert forbidden not in used, f"{forbidden} belongs to weekly_activity_publish"
