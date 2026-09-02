import gzip
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from collector.gharchive.historical import (
    HISTORICAL_CUTOFF,
    HISTORICAL_START,
    ArchiveValidationError,
    HistoricalDownloader,
    RangeValidationError,
    archive_for_hour,
    expected_archives,
    format_utc_hour,
    validate_downloaded_range,
)


def gzip_payload(label: str) -> bytes:
    return gzip.compress(f'{{"hour":"{label}"}}\n'.encode())


@dataclass
class FakeResponse:
    payload: bytes
    status: int = 200
    content_length: int | None = None
    interrupt_after_first_chunk: bool = False
    position: int = 0
    read_count: int = 0
    closed: bool = False
    headers: dict[str, str] = field(init=False)

    def __post_init__(self) -> None:
        length = (
            len(self.payload) if self.content_length is None else self.content_length
        )
        self.headers = {"Content-Length": str(length)}

    def read(self, size: int = -1) -> bytes:
        if self.interrupt_after_first_chunk and self.read_count > 0:
            raise InterruptedError("simulated operator interruption")
        self.read_count += 1
        if self.position >= len(self.payload):
            return b""
        end = len(self.payload) if size < 0 else self.position + size
        chunk = self.payload[self.position : end]
        self.position += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


class ScriptedTransport:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = list(responses)
        self.urls: list[str] = []

    def open(self, url: str, timeout: float) -> FakeResponse:
        self.urls.append(url)
        if not self.responses:
            raise AssertionError("unexpected HTTP request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_august_plan_is_744_exclusive_utc_hours() -> None:
    archives = expected_archives(HISTORICAL_START, HISTORICAL_CUTOFF)

    assert len(archives) == 744
    assert archives[0].filename == "2026-08-01-0.json.gz"
    assert archives[-1].filename == "2026-08-31-23.json.gz"
    assert archives[0].relative_path.as_posix() == (
        "raw/gharchive/dt=2026-08-01/2026-08-01-0.json.gz"
    )
    assert archives[-1].hour + timedelta(hours=1) == HISTORICAL_CUTOFF


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (HISTORICAL_START - timedelta(hours=1), HISTORICAL_START),
        (HISTORICAL_CUTOFF, HISTORICAL_CUTOFF + timedelta(hours=1)),
        (HISTORICAL_START, HISTORICAL_CUTOFF + timedelta(hours=1)),
    ],
)
def test_out_of_contract_range_is_rejected_before_http(
    tmp_path: Path,
    start: datetime,
    end: datetime,
) -> None:
    transport = ScriptedTransport([])
    downloader = HistoricalDownloader(tmp_path, transport=transport)

    with pytest.raises(RangeValidationError):
        downloader.download(start, end)

    assert transport.urls == []
    assert not (tmp_path / "checkpoint.json").exists()


def test_download_then_rerun_reuses_exact_raw_bytes(tmp_path: Path) -> None:
    payload = gzip_payload("00")
    transport = ScriptedTransport([FakeResponse(payload)])
    downloader = HistoricalDownloader(tmp_path, transport=transport)
    end = HISTORICAL_START + timedelta(hours=1)

    first = downloader.download(HISTORICAL_START, end)
    second = downloader.download(HISTORICAL_START, end)
    archive = archive_for_hour(HISTORICAL_START)

    assert first.downloaded == (format_utc_hour(HISTORICAL_START),)
    assert first.reused == ()
    assert first.missing == ()
    assert second.downloaded == ()
    assert second.reused == (format_utc_hour(HISTORICAL_START),)
    assert len(transport.urls) == 1
    assert archive.final_path(tmp_path).read_bytes() == payload
    assert not archive.partial_path(tmp_path).exists()
    checkpoint = json.loads((tmp_path / "checkpoint.json").read_text())
    record = checkpoint["hours"][format_utc_hour(HISTORICAL_START)]
    assert record["status"] == "complete"
    assert record["gzip_valid"] is True
    assert record["location"] == archive.relative_path.as_posix()


def test_valid_final_without_checkpoint_is_reconciled_without_http(
    tmp_path: Path,
) -> None:
    archive = archive_for_hour(HISTORICAL_START)
    final_path = archive.final_path(tmp_path)
    final_path.parent.mkdir(parents=True)
    final_path.write_bytes(gzip_payload("already-published"))
    transport = ScriptedTransport([])

    summary = HistoricalDownloader(tmp_path, transport=transport).download(
        HISTORICAL_START,
        HISTORICAL_START + timedelta(hours=1),
    )

    assert summary.reused == (format_utc_hour(HISTORICAL_START),)
    assert transport.urls == []
    assert (tmp_path / "checkpoint.json").is_file()


def test_checkpoint_without_final_redownloads_file(tmp_path: Path) -> None:
    end = HISTORICAL_START + timedelta(hours=1)
    first_payload = gzip_payload("first")
    HistoricalDownloader(
        tmp_path,
        transport=ScriptedTransport([FakeResponse(first_payload)]),
    ).download(HISTORICAL_START, end)
    archive_for_hour(HISTORICAL_START).final_path(tmp_path).unlink()
    second_payload = gzip_payload("second")
    transport = ScriptedTransport([FakeResponse(second_payload)])

    summary = HistoricalDownloader(tmp_path, transport=transport).download(
        HISTORICAL_START,
        end,
    )

    assert summary.downloaded == (format_utc_hour(HISTORICAL_START),)
    assert len(transport.urls) == 1
    assert archive_for_hour(HISTORICAL_START).final_path(tmp_path).read_bytes() == (
        second_payload
    )


def test_interrupted_partial_is_ignored_and_next_run_resumes(tmp_path: Path) -> None:
    payload = gzip_payload("resume")
    transport = ScriptedTransport(
        [
            FakeResponse(payload, interrupt_after_first_chunk=True),
            FakeResponse(payload),
        ]
    )
    downloader = HistoricalDownloader(tmp_path, transport=transport, chunk_size=4)
    end = HISTORICAL_START + timedelta(hours=1)
    archive = archive_for_hour(HISTORICAL_START)

    with pytest.raises(InterruptedError):
        downloader.download(HISTORICAL_START, end)

    assert archive.partial_path(tmp_path).is_file()
    assert not archive.final_path(tmp_path).exists()

    summary = downloader.download(HISTORICAL_START, end)

    assert summary.downloaded == (format_utc_hour(HISTORICAL_START),)
    assert summary.missing == ()
    assert archive.final_path(tmp_path).read_bytes() == payload
    assert not archive.partial_path(tmp_path).exists()
    assert len(transport.urls) == 2


def test_missing_check_ignores_part_files_and_reports_exact_hour(
    tmp_path: Path,
) -> None:
    first = archive_for_hour(HISTORICAL_START)
    second_hour = HISTORICAL_START + timedelta(hours=1)
    second = archive_for_hour(second_hour)
    first.final_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    first.final_path(tmp_path).write_bytes(gzip_payload("00"))
    second.partial_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    second.partial_path(tmp_path).write_bytes(b"partial")

    summary = validate_downloaded_range(
        tmp_path,
        HISTORICAL_START,
        HISTORICAL_START + timedelta(hours=2),
    )

    assert summary.completed == (format_utc_hour(HISTORICAL_START),)
    assert summary.missing == (format_utc_hour(second_hour),)
    assert summary.invalid == {}


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(gzip_payload("short"), content_length=999),
        FakeResponse(b"not-a-gzip"),
    ],
)
def test_invalid_response_never_becomes_final(
    tmp_path: Path,
    response: FakeResponse,
) -> None:
    downloader = HistoricalDownloader(
        tmp_path,
        transport=ScriptedTransport([response]),
        max_attempts=1,
    )
    archive = archive_for_hour(HISTORICAL_START)

    summary = downloader.download(
        HISTORICAL_START,
        HISTORICAL_START + timedelta(hours=1),
    )

    assert summary.downloaded == ()
    assert summary.missing == (format_utc_hour(HISTORICAL_START),)
    assert summary.failed
    assert not archive.final_path(tmp_path).exists()
    assert archive.partial_path(tmp_path).exists()


def test_retryable_http_status_then_success_records_one_file(tmp_path: Path) -> None:
    delays: list[float] = []
    transport = ScriptedTransport(
        [FakeResponse(b"", status=503), FakeResponse(gzip_payload("retry"))]
    )
    downloader = HistoricalDownloader(
        tmp_path,
        transport=transport,
        max_attempts=2,
        backoff_seconds=0.25,
        sleep=delays.append,
    )

    summary = downloader.download(
        HISTORICAL_START,
        HISTORICAL_START + timedelta(hours=1),
    )

    assert summary.downloaded == (format_utc_hour(HISTORICAL_START),)
    assert summary.failed == {}
    assert len(transport.urls) == 2
    assert delays == [0.25]


def test_gzip_validator_rejects_corrupt_completed_file(tmp_path: Path) -> None:
    archive = archive_for_hour(HISTORICAL_START)
    final_path = archive.final_path(tmp_path)
    final_path.parent.mkdir(parents=True)
    final_path.write_bytes(b"not-gzip")

    summary = validate_downloaded_range(
        tmp_path,
        HISTORICAL_START,
        HISTORICAL_START + timedelta(hours=1),
    )

    assert summary.completed == ()
    assert summary.missing == ()
    assert format_utc_hour(HISTORICAL_START) in summary.invalid
    assert "invalid gzip archive" in next(iter(summary.invalid.values()))
    assert summary.as_dict()["invalid_archives"] == dict(summary.invalid)


def test_missing_and_invalid_are_counted_separately(tmp_path: Path) -> None:
    """An absent hour is a gap; a corrupt file is not. They must not overlap."""

    present = archive_for_hour(HISTORICAL_START)
    corrupt_hour = HISTORICAL_START + timedelta(hours=1)
    corrupt = archive_for_hour(corrupt_hour)
    absent_hour = HISTORICAL_START + timedelta(hours=2)
    present.final_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    present.final_path(tmp_path).write_bytes(gzip_payload("00"))
    corrupt.final_path(tmp_path).write_bytes(b"not-gzip")

    summary = validate_downloaded_range(
        tmp_path,
        HISTORICAL_START,
        HISTORICAL_START + timedelta(hours=3),
    )

    assert summary.completed == (format_utc_hour(HISTORICAL_START),)
    assert summary.missing == (format_utc_hour(absent_hour),)
    assert set(summary.invalid) == {format_utc_hour(corrupt_hour)}
    assert not set(summary.missing) & set(summary.invalid)
    assert summary.expected == (
        len(summary.completed) + len(summary.missing) + len(summary.invalid)
    )


def test_archive_helpers_reject_naive_or_unaligned_hours() -> None:
    with pytest.raises(RangeValidationError, match="timezone"):
        archive_for_hour(datetime(2026, 8, 1))  # noqa: DTZ001 - rejection case
    with pytest.raises(RangeValidationError, match="aligned"):
        archive_for_hour(datetime(2026, 8, 1, 0, 1, tzinfo=UTC))
    with pytest.raises(RangeValidationError, match="timezone"):
        format_utc_hour(datetime(2026, 8, 1))  # noqa: DTZ001 - rejection case


def test_validation_error_type_is_not_silently_treated_as_success() -> None:
    error = ArchiveValidationError("broken archive")

    assert str(error) == "broken archive"
