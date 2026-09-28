"""WebHdfsSink tests. No network: every case uses a recording fake transport."""

import gzip
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from collector.gharchive.historical import HISTORICAL_START, archive_for_hour
from collector.gharchive.sinks import (
    DEFAULT_RAW_ROOT,
    HdfsSinkError,
    WebHdfsResponse,
    WebHdfsSink,
    publish_downloaded_range,
)

BASE_URL = "http://hdfs-namenode:9870/webhdfs/v1"
HOUR = datetime(2026, 8, 1, tzinfo=UTC)
FILENAME = "2026-08-01-0.json.gz"
DESTINATION = f"{DEFAULT_RAW_ROOT}/gharchive/dt=2026-08-01/{FILENAME}"
REDIRECT = "http://hdfs-datanode:9864/webhdfs/v1/upload"


def boolean_body(value: bool) -> bytes:
    return json.dumps({"boolean": value}).encode()


@dataclass
class FakeTransport:
    """Answers WebHDFS operations from a scripted map and records every call."""

    exists: bool = False
    mkdirs: WebHdfsResponse | None = None
    create: WebHdfsResponse | None = None
    upload: WebHdfsResponse | None = None
    rename: WebHdfsResponse | None = None
    calls: list[tuple[str, str, Path | None]] = field(default_factory=list)

    def request(
        self,
        method: str,
        url: str,
        *,
        body: Path | None = None,
        timeout: float,
    ) -> WebHdfsResponse:
        assert timeout > 0
        self.calls.append((method, url, body))
        if url == REDIRECT:
            return self.upload or WebHdfsResponse(201, {}, b"")
        operation = url.rsplit("op=", 1)[1].split("&", 1)[0]
        if operation == "GETFILESTATUS":
            if self.exists:
                return WebHdfsResponse(200, {}, b'{"FileStatus":{}}')
            return WebHdfsResponse(404, {}, b'{"RemoteException":{}}')
        if operation == "MKDIRS":
            return self.mkdirs or WebHdfsResponse(200, {}, boolean_body(True))
        if operation == "CREATE":
            return self.create or WebHdfsResponse(307, {"Location": REDIRECT}, b"")
        if operation == "RENAME":
            return self.rename or WebHdfsResponse(200, {}, boolean_body(True))
        if operation == "DELETE":
            return WebHdfsResponse(200, {}, boolean_body(True))
        raise AssertionError(f"unexpected WebHDFS operation: {operation}")

    def operations(self) -> list[str]:
        return [
            "UPLOAD" if url == REDIRECT else url.rsplit("op=", 1)[1].split("&", 1)[0]
            for _, url, _ in self.calls
        ]


def raw_file(tmp_path: Path, name: str = FILENAME) -> Path:
    path = tmp_path / name
    path.write_bytes(gzip.compress(b'{"type":"PushEvent"}\n'))
    return path


def test_base_url_is_normalised_and_validated() -> None:
    assert WebHdfsSink(base_url=f"{BASE_URL}/").base_url == BASE_URL
    for invalid in ("", "   ", "hdfs://nn/webhdfs/v1", f"{BASE_URL}?op=OPEN"):
        with pytest.raises(ValueError):
            WebHdfsSink(base_url=invalid)
    with pytest.raises(ValueError):
        WebHdfsSink(base_url=BASE_URL, timeout=0)


def test_destination_path_uses_canonical_raw_root(tmp_path: Path) -> None:
    transport = FakeTransport()
    sink = WebHdfsSink(base_url=BASE_URL, transport=transport)

    assert sink.store(raw_file(tmp_path), HOUR) == f"hdfs://{DESTINATION}"
    assert transport.operations() == [
        "GETFILESTATUS",
        "MKDIRS",
        "CREATE",
        "UPLOAD",
        "RENAME",
    ]

    status_url = transport.calls[0][1]
    assert status_url.startswith(f"{BASE_URL}{DESTINATION}?")
    assert "user.name=hadoop" in status_url

    mkdirs_url = transport.calls[1][1]
    assert f"{DEFAULT_RAW_ROOT}/gharchive/dt=2026-08-01?" in mkdirs_url


def test_existing_destination_is_reused_without_upload(tmp_path: Path) -> None:
    transport = FakeTransport(exists=True)
    sink = WebHdfsSink(base_url=BASE_URL, transport=transport)

    assert sink.store(raw_file(tmp_path), HOUR) == f"hdfs://{DESTINATION}"
    assert transport.operations() == ["GETFILESTATUS"]


def test_upload_goes_to_a_temporary_path_then_renames(tmp_path: Path) -> None:
    local_path = raw_file(tmp_path)
    transport = FakeTransport()

    WebHdfsSink(base_url=BASE_URL, transport=transport).store(local_path, HOUR)

    create_url = transport.calls[2][1]
    assert f"{DESTINATION}.uploading-" in create_url
    assert "op=CREATE" in create_url
    assert "overwrite=false" in create_url

    # The body is streamed to the DataNode redirect target, not to the NameNode.
    assert transport.calls[3] == ("PUT", REDIRECT, local_path)

    rename_url = transport.calls[4][1]
    assert f"{DESTINATION}.uploading-" in rename_url
    assert (
        f"destination={DESTINATION.replace('/', '%2F').replace('=', '%3D')}"
        in rename_url
    )


def test_repeated_store_is_idempotent_across_sink_instances(tmp_path: Path) -> None:
    local_path = raw_file(tmp_path)
    first = FakeTransport()
    WebHdfsSink(base_url=BASE_URL, transport=first).store(local_path, HOUR)
    assert first.operations().count("UPLOAD") == 1

    second = FakeTransport(exists=True)
    WebHdfsSink(base_url=BASE_URL, transport=second).store(local_path, HOUR)
    assert second.operations().count("UPLOAD") == 0


def test_missing_local_file_is_rejected_before_any_request(tmp_path: Path) -> None:
    transport = FakeTransport()
    with pytest.raises(HdfsSinkError, match="local Raw file is missing"):
        WebHdfsSink(base_url=BASE_URL, transport=transport).store(
            tmp_path / "absent.json.gz",
            HOUR,
        )
    assert transport.calls == []


def test_upload_failure_removes_the_temporary_object(tmp_path: Path) -> None:
    transport = FakeTransport(upload=WebHdfsResponse(500, {}, b"datanode exploded"))

    with pytest.raises(HdfsSinkError, match="upload temporary Raw file"):
        WebHdfsSink(base_url=BASE_URL, transport=transport).store(
            raw_file(tmp_path),
            HOUR,
        )

    assert transport.operations()[-1] == "DELETE"
    assert f"{DESTINATION}.uploading-" in transport.calls[-1][1]


def test_rename_failure_removes_the_temporary_object(tmp_path: Path) -> None:
    transport = FakeTransport(rename=WebHdfsResponse(200, {}, boolean_body(False)))

    with pytest.raises(HdfsSinkError, match="publish Raw file"):
        WebHdfsSink(base_url=BASE_URL, transport=transport).store(
            raw_file(tmp_path),
            HOUR,
        )

    assert transport.operations() == [
        "GETFILESTATUS",
        "MKDIRS",
        "CREATE",
        "UPLOAD",
        "RENAME",
        "DELETE",
    ]


def test_missing_redirect_location_is_reported(tmp_path: Path) -> None:
    transport = FakeTransport(create=WebHdfsResponse(307, {}, b""))

    with pytest.raises(HdfsSinkError, match="no redirect Location"):
        WebHdfsSink(base_url=BASE_URL, transport=transport).store(
            raw_file(tmp_path),
            HOUR,
        )

    assert transport.operations()[-1] == "DELETE"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"mkdirs": WebHdfsResponse(403, {}, b"denied")}, "create Raw partition"),
        (
            {"mkdirs": WebHdfsResponse(200, {}, boolean_body(False))},
            "create Raw partition",
        ),
        ({"create": WebHdfsResponse(500, {}, b"boom")}, "open temporary Raw file"),
    ],
)
def test_http_errors_are_reported_with_status(
    tmp_path: Path,
    kwargs: dict[str, WebHdfsResponse],
    message: str,
) -> None:
    transport = FakeTransport(**kwargs)
    with pytest.raises(HdfsSinkError, match=message):
        WebHdfsSink(base_url=BASE_URL, transport=transport).store(
            raw_file(tmp_path),
            HOUR,
        )


def test_unexpected_status_check_is_not_treated_as_absent(tmp_path: Path) -> None:
    class BrokenStatus(FakeTransport):
        def request(self, method, url, *, body=None, timeout):  # type: ignore[no-untyped-def]
            self.calls.append((method, url, body))
            return WebHdfsResponse(503, {}, b"namenode unavailable")

    transport = BrokenStatus()
    with pytest.raises(HdfsSinkError, match="check destination"):
        WebHdfsSink(base_url=BASE_URL, transport=transport).store(
            raw_file(tmp_path),
            HOUR,
        )
    assert len(transport.calls) == 1


def test_publish_range_separates_uploaded_reused_missing_and_invalid(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "out"
    hours = [HISTORICAL_START + timedelta(hours=index) for index in range(3)]
    archives = [archive_for_hour(hour) for hour in hours]
    archives[0].final_path(output_root).parent.mkdir(parents=True, exist_ok=True)
    archives[0].final_path(output_root).write_bytes(gzip.compress(b'{"a":1}\n'))
    archives[1].final_path(output_root).write_bytes(b"not-gzip")
    # archives[2] intentionally absent

    class RecordingSink:
        def __init__(self) -> None:
            self.stored: list[str] = []

        def exists(self, hour: datetime, filename: str) -> bool:
            return False

        def store(self, local_path: Path, hour: datetime) -> str:
            self.stored.append(local_path.name)
            return f"hdfs://{DEFAULT_RAW_ROOT}/gharchive/x/{local_path.name}"

    sink = RecordingSink()
    summary = publish_downloaded_range(
        sink,
        output_root,
        HISTORICAL_START,
        HISTORICAL_START + timedelta(hours=3),
    )

    assert summary.expected == 3
    assert len(summary.uploaded) == 1
    assert len(summary.invalid) == 1
    assert len(summary.missing) == 1
    assert summary.reused == ()
    assert summary.failed == {}
    # A corrupt local archive is never handed to the sink.
    assert sink.stored == [archives[0].filename]
    assert summary.expected == (
        len(summary.uploaded)
        + len(summary.reused)
        + len(summary.missing)
        + len(summary.invalid)
        + len(summary.failed)
    )
    assert summary.as_dict()["invalid_archives"]


def test_publish_range_reuses_hours_already_in_hdfs(tmp_path: Path) -> None:
    output_root = tmp_path / "out"
    archive = archive_for_hour(HISTORICAL_START)
    archive.final_path(output_root).parent.mkdir(parents=True, exist_ok=True)
    archive.final_path(output_root).write_bytes(gzip.compress(b'{"a":1}\n'))

    class AlreadyThere:
        def exists(self, hour: datetime, filename: str) -> bool:
            return True

        def store(self, local_path: Path, hour: datetime) -> str:
            raise AssertionError("store must not run for an existing hour")

    summary = publish_downloaded_range(
        AlreadyThere(),
        output_root,
        HISTORICAL_START,
        HISTORICAL_START + timedelta(hours=1),
    )

    assert summary.reused == ("2026-08-01T00:00:00Z",)
    assert summary.uploaded == ()
    assert summary.published_bytes == 0


def test_publish_range_skips_validation_for_hours_already_in_hdfs(
    tmp_path: Path,
) -> None:
    """A published hour is not decompressed again, even if the local copy rots."""

    output_root = tmp_path / "out"
    archive = archive_for_hour(HISTORICAL_START)
    archive.final_path(output_root).parent.mkdir(parents=True, exist_ok=True)
    archive.final_path(output_root).write_bytes(b"not-gzip-any-more")

    class AlreadyThere:
        def exists(self, hour: datetime, filename: str) -> bool:
            return True

        def store(self, local_path: Path, hour: datetime) -> str:
            raise AssertionError("store must not run for an existing hour")

    summary = publish_downloaded_range(
        AlreadyThere(),
        output_root,
        HISTORICAL_START,
        HISTORICAL_START + timedelta(hours=1),
    )

    assert summary.reused == ("2026-08-01T00:00:00Z",)
    assert summary.invalid == {}


def test_publish_range_reports_existence_check_failure(tmp_path: Path) -> None:
    output_root = tmp_path / "out"
    archive = archive_for_hour(HISTORICAL_START)
    archive.final_path(output_root).parent.mkdir(parents=True, exist_ok=True)
    archive.final_path(output_root).write_bytes(gzip.compress(b'{"a":1}\n'))

    class UnreachableSink:
        def exists(self, hour: datetime, filename: str) -> bool:
            raise HdfsSinkError("failed to check destination (HTTP 503): down")

        def store(self, local_path: Path, hour: datetime) -> str:
            raise AssertionError("store must not run when the check fails")

    summary = publish_downloaded_range(
        UnreachableSink(),
        output_root,
        HISTORICAL_START,
        HISTORICAL_START + timedelta(hours=1),
    )

    assert len(summary.failed) == 1
    assert summary.uploaded == ()


def test_publish_range_records_sink_failure_without_aborting(tmp_path: Path) -> None:
    output_root = tmp_path / "out"
    for index in range(2):
        archive = archive_for_hour(HISTORICAL_START + timedelta(hours=index))
        archive.final_path(output_root).parent.mkdir(parents=True, exist_ok=True)
        archive.final_path(output_root).write_bytes(gzip.compress(b'{"a":1}\n'))

    class FlakySink:
        def __init__(self) -> None:
            self.attempts = 0

        def exists(self, hour: datetime, filename: str) -> bool:
            return False

        def store(self, local_path: Path, hour: datetime) -> str:
            self.attempts += 1
            if self.attempts == 1:
                raise HdfsSinkError("failed to publish Raw file (HTTP 500): boom")
            return f"hdfs://{DEFAULT_RAW_ROOT}/gharchive/x/{local_path.name}"

    summary = publish_downloaded_range(
        FlakySink(),
        output_root,
        HISTORICAL_START,
        HISTORICAL_START + timedelta(hours=2),
    )

    assert len(summary.failed) == 1
    assert len(summary.uploaded) == 1
