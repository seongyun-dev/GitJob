import json
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from collector.gharchive.__main__ import main
from collector.gharchive.historical import RangeValidationError
from collector.gharchive.sinks import HdfsCliSink, HdfsSinkError, hdfs_raw_path


def test_plan_cli_reports_full_august_without_downloading(capsys) -> None:
    exit_code = main(["plan"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload == {
        "historical_start": "2026-08-01T00:00:00Z",
        "historical_cutoff": "2026-09-01T00:00:00Z",
        "requested_start": "2026-08-01T00:00:00Z",
        "requested_end": "2026-09-01T00:00:00Z",
        "expected_files": 744,
        "first_filename": "2026-08-01-0.json.gz",
        "last_filename": "2026-08-31-23.json.gz",
    }


def test_download_cli_rejects_cutoff_overrun_without_creating_output(
    tmp_path: Path,
    capsys,
) -> None:
    output_root = tmp_path / "must-not-exist"

    exit_code = main(
        [
            "download",
            "--start",
            "2026-09-01T00:00:00Z",
            "--end",
            "2026-09-01T01:00:00Z",
            "--output-root",
            str(output_root),
        ]
    )

    error = json.loads(capsys.readouterr().err)
    assert exit_code == 2
    assert "historical_cutoff" in error["error"]
    assert not output_root.exists()


def test_hdfs_raw_path_uses_source_and_utc_date_partition() -> None:
    path = hdfs_raw_path(
        datetime(2026, 8, 1, 0, tzinfo=UTC),
        "2026-08-01-0.json.gz",
    )

    assert path.as_posix() == (
        "/gitjob/raw/gharchive/dt=2026-08-01/2026-08-01-0.json.gz"
    )


@pytest.mark.parametrize(
    ("hour", "filename", "error"),
    [
        (
            datetime(2026, 8, 1),  # noqa: DTZ001 - naive input must be rejected
            "2026-08-01-0.json.gz",
            RangeValidationError,
        ),
        (
            datetime(2026, 8, 1, 0, 1, tzinfo=UTC),
            "2026-08-01-0.json.gz",
            RangeValidationError,
        ),
        (datetime(2026, 8, 1, tzinfo=UTC), "../escape.json.gz", ValueError),
    ],
)
def test_hdfs_raw_path_rejects_ambiguous_inputs(
    hour: datetime,
    filename: str,
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        hdfs_raw_path(hour, filename)


def test_hdfs_sink_uses_temp_then_atomic_publish(tmp_path: Path) -> None:
    local_path = tmp_path / "2026-08-01-0.json.gz"
    local_path.write_bytes(b"opaque-raw-bytes")
    commands: list[tuple[str, ...]] = []

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        normalized = tuple(command)
        commands.append(normalized)
        return_code = 1 if normalized[2:4] == ("-test", "-e") else 0
        return subprocess.CompletedProcess(normalized, return_code, "", "")

    location = HdfsCliSink(runner=runner).store(
        local_path,
        datetime(2026, 8, 1, tzinfo=UTC),
    )

    destination = "/gitjob/raw/gharchive/dt=2026-08-01/2026-08-01-0.json.gz"
    assert location == f"hdfs://{destination}"
    assert commands[0] == ("hdfs", "dfs", "-test", "-e", destination)
    assert commands[1] == (
        "hdfs",
        "dfs",
        "-mkdir",
        "-p",
        "/gitjob/raw/gharchive/dt=2026-08-01",
    )
    assert commands[2][:3] == ("hdfs", "dfs", "-put")
    assert commands[2][3] == str(local_path)
    assert commands[2][4].startswith(f"{destination}.uploading-")
    assert commands[3] == (
        "hdfs",
        "dfs",
        "-mv",
        commands[2][4],
        destination,
    )


def test_hdfs_sink_removes_temporary_file_when_publish_fails(tmp_path: Path) -> None:
    """A failed publish must not leave an .uploading- object behind in HDFS."""

    local_path = tmp_path / "2026-08-01-0.json.gz"
    local_path.write_bytes(b"opaque-raw-bytes")
    commands: list[tuple[str, ...]] = []

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        normalized = tuple(command)
        commands.append(normalized)
        if normalized[2:4] == ("-test", "-e"):
            return subprocess.CompletedProcess(normalized, 1, "", "")
        if normalized[2] == "-mv":
            return subprocess.CompletedProcess(normalized, 1, "", "publish failed")
        return subprocess.CompletedProcess(normalized, 0, "", "")

    with pytest.raises(HdfsSinkError, match="publish Raw file"):
        HdfsCliSink(runner=runner).store(
            local_path,
            datetime(2026, 8, 1, tzinfo=UTC),
        )

    temporary = commands[2][4]
    assert commands[-1] == ("hdfs", "dfs", "-rm", "-f", "-skipTrash", temporary)


def test_hdfs_sink_reuses_existing_destination(tmp_path: Path) -> None:
    local_path = tmp_path / "2026-08-01-0.json.gz"
    local_path.write_bytes(b"opaque-raw-bytes")
    commands: list[tuple[str, ...]] = []

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        normalized = tuple(command)
        commands.append(normalized)
        return subprocess.CompletedProcess(normalized, 0, "", "")

    location = HdfsCliSink(runner=runner).store(
        local_path,
        datetime(2026, 8, 1, tzinfo=UTC),
    )

    assert location == (
        "hdfs:///gitjob/raw/gharchive/dt=2026-08-01/2026-08-01-0.json.gz"
    )
    assert len(commands) == 1
    assert commands[0][2:4] == ("-test", "-e")
