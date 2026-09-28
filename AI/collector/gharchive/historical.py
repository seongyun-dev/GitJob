"""Resumable, byte-preserving GH Archive historical downloader."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

SOURCE = "gharchive"
DEFAULT_BASE_URL = "https://data.gharchive.org"
HISTORICAL_START = datetime(2026, 8, 1, tzinfo=UTC)
HISTORICAL_CUTOFF = datetime(2026, 9, 1, tzinfo=UTC)
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[3] / ".local" / SOURCE
CHECKPOINT_VERSION = 1
CHUNK_SIZE = 1024 * 1024


class RangeValidationError(ValueError):
    """Raised when a requested historical range violates its UTC contract."""


class ArchiveValidationError(RuntimeError):
    """Raised when a downloaded archive is incomplete or invalid."""


class CheckpointError(RuntimeError):
    """Raised when checkpoint state cannot be trusted."""


class HttpStatusError(RuntimeError):
    """HTTP response with a non-success status."""

    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"HTTP {status} for {url}")
        self.status = status


class ResponseStream(Protocol):
    status: int
    headers: Mapping[str, str]

    def read(self, size: int = -1) -> bytes: ...

    def close(self) -> None: ...


class HttpTransport(Protocol):
    def open(self, url: str, timeout: float) -> ResponseStream: ...


class UrllibTransport:
    """Small stdlib transport so runtime dependencies remain unchanged."""

    def open(self, url: str, timeout: float) -> ResponseStream:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "GitJob-GHArchive-Historical/1.0"},
        )
        return urllib.request.urlopen(request, timeout=timeout)  # type: ignore[return-value]


@dataclass(frozen=True)
class ArchiveFile:
    """One immutable GH Archive UTC-hour object and its local Raw location."""

    hour: datetime
    filename: str
    url: str
    relative_path: Path

    def final_path(self, output_root: Path) -> Path:
        return output_root / self.relative_path

    def partial_path(self, output_root: Path) -> Path:
        final_path = self.final_path(output_root)
        return final_path.with_name(f"{final_path.name}.part")


@dataclass(frozen=True)
class FileValidation:
    compressed_bytes: int
    uncompressed_bytes: int
    sha256: str


@dataclass(frozen=True)
class DownloadSummary:
    expected: int
    downloaded: tuple[str, ...]
    reused: tuple[str, ...]
    failed: Mapping[str, str]
    missing: tuple[str, ...]
    downloaded_bytes: int
    validated_uncompressed_bytes: int

    @property
    def completed(self) -> int:
        return self.expected - len(self.missing)

    def as_dict(self) -> dict[str, object]:
        return {
            "expected": self.expected,
            "completed": self.completed,
            "downloaded": len(self.downloaded),
            "reused": len(self.reused),
            "failed": len(self.failed),
            "missing": len(self.missing),
            "downloaded_hours": list(self.downloaded),
            "reused_hours": list(self.reused),
            "failures": dict(self.failed),
            "missing_hours": list(self.missing),
            "downloaded_bytes": self.downloaded_bytes,
            "validated_uncompressed_bytes": self.validated_uncompressed_bytes,
        }


@dataclass(frozen=True)
class ValidationSummary:
    """Hour-gap and archive-corruption results, counted separately.

    ``missing`` holds hours with no file at all, ``invalid`` holds hours whose
    file exists but failed gzip validation. The two never overlap, so
    ``expected == len(completed) + len(missing) + len(invalid)``.
    """

    expected: int
    completed: tuple[str, ...]
    missing: tuple[str, ...]
    invalid: Mapping[str, str]
    compressed_bytes: int
    uncompressed_bytes: int

    def as_dict(self) -> dict[str, object]:
        return {
            "expected": self.expected,
            "completed": len(self.completed),
            "missing": len(self.missing),
            "invalid": len(self.invalid),
            "completed_hours": list(self.completed),
            "missing_hours": list(self.missing),
            "invalid_archives": dict(self.invalid),
            "compressed_bytes": self.compressed_bytes,
            "uncompressed_bytes": self.uncompressed_bytes,
        }


def parse_utc_hour(value: str) -> datetime:
    """Parse an aware ISO-8601 timestamp and require an exact UTC hour."""

    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise RangeValidationError(f"invalid ISO-8601 timestamp: {value}") from exc

    if parsed.tzinfo is None:
        raise RangeValidationError(f"timestamp must include a timezone: {value}")

    parsed = parsed.astimezone(UTC)
    if any((parsed.minute, parsed.second, parsed.microsecond)):
        raise RangeValidationError(f"timestamp must be aligned to an hour: {value}")
    return parsed


def format_utc_hour(value: datetime) -> str:
    if value.tzinfo is None:
        raise RangeValidationError("timestamp must include a timezone")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:00:00Z")


def validate_requested_range(
    start: datetime,
    end: datetime,
    *,
    historical_start: datetime = HISTORICAL_START,
    historical_cutoff: datetime = HISTORICAL_CUTOFF,
) -> None:
    values = {
        "start": start,
        "end": end,
        "historical_start": historical_start,
        "historical_cutoff": historical_cutoff,
    }
    for name, value in values.items():
        if value.tzinfo is None:
            raise RangeValidationError(f"{name} must include a timezone")
        utc_value = value.astimezone(UTC)
        if any((utc_value.minute, utc_value.second, utc_value.microsecond)):
            raise RangeValidationError(f"{name} must be aligned to an hour")

    start = start.astimezone(UTC)
    end = end.astimezone(UTC)
    historical_start = historical_start.astimezone(UTC)
    historical_cutoff = historical_cutoff.astimezone(UTC)

    if historical_start >= historical_cutoff:
        raise RangeValidationError("historical_start must be before cutoff")
    if start < historical_start:
        raise RangeValidationError(
            "requested start precedes historical_start: "
            f"{format_utc_hour(start)} < {format_utc_hour(historical_start)}"
        )
    if start >= end:
        raise RangeValidationError("start must be before end")
    if end > historical_cutoff:
        raise RangeValidationError(
            "requested end exceeds exclusive historical_cutoff: "
            f"{format_utc_hour(end)} > {format_utc_hour(historical_cutoff)}"
        )


def iter_utc_hours(
    start: datetime,
    end: datetime,
    *,
    historical_start: datetime = HISTORICAL_START,
    historical_cutoff: datetime = HISTORICAL_CUTOFF,
) -> Iterator[datetime]:
    validate_requested_range(
        start,
        end,
        historical_start=historical_start,
        historical_cutoff=historical_cutoff,
    )
    cursor = start.astimezone(UTC)
    end = end.astimezone(UTC)
    while cursor < end:
        yield cursor
        cursor += timedelta(hours=1)


def archive_for_hour(
    hour: datetime,
    *,
    base_url: str = DEFAULT_BASE_URL,
    source: str = SOURCE,
) -> ArchiveFile:
    if hour.tzinfo is None:
        raise RangeValidationError("archive hour must include a timezone")
    hour = hour.astimezone(UTC)
    if any((hour.minute, hour.second, hour.microsecond)):
        raise RangeValidationError("archive hour must be aligned to an hour")
    filename = f"{hour:%Y-%m-%d}-{hour.hour}.json.gz"
    return ArchiveFile(
        hour=hour,
        filename=filename,
        url=f"{base_url.rstrip('/')}/{filename}",
        relative_path=Path("raw") / source / f"dt={hour:%Y-%m-%d}" / filename,
    )


def expected_archives(
    start: datetime,
    end: datetime,
    *,
    historical_start: datetime = HISTORICAL_START,
    historical_cutoff: datetime = HISTORICAL_CUTOFF,
    base_url: str = DEFAULT_BASE_URL,
) -> tuple[ArchiveFile, ...]:
    return tuple(
        archive_for_hour(hour, base_url=base_url)
        for hour in iter_utc_hours(
            start,
            end,
            historical_start=historical_start,
            historical_cutoff=historical_cutoff,
        )
    )


def validate_gzip_file(path: Path) -> FileValidation:
    """Read compressed and decompressed streams fully, including the gzip CRC."""

    if not path.is_file():
        raise ArchiveValidationError(f"archive file is missing: {path}")

    digest = hashlib.sha256()
    compressed_bytes = 0
    with path.open("rb") as raw_stream:
        while chunk := raw_stream.read(CHUNK_SIZE):
            digest.update(chunk)
            compressed_bytes += len(chunk)
    if compressed_bytes == 0:
        raise ArchiveValidationError(f"archive file is empty: {path}")

    uncompressed_bytes = 0
    try:
        with gzip.open(path, "rb") as gzip_stream:
            while chunk := gzip_stream.read(CHUNK_SIZE):
                uncompressed_bytes += len(chunk)
    except (EOFError, OSError) as exc:
        raise ArchiveValidationError(f"invalid gzip archive: {path}") from exc
    if uncompressed_bytes == 0:
        raise ArchiveValidationError(f"gzip payload is empty: {path}")

    return FileValidation(
        compressed_bytes=compressed_bytes,
        uncompressed_bytes=uncompressed_bytes,
        sha256=digest.hexdigest(),
    )


class CheckpointStore:
    """Atomic JSON checkpoint containing acquisition metadata, never event data."""

    def __init__(
        self,
        path: Path,
        *,
        historical_start: datetime,
        historical_cutoff: datetime,
    ) -> None:
        self.path = path
        self.historical_start = historical_start
        self.historical_cutoff = historical_cutoff
        self.data = self._load()

    def _load(self) -> dict[str, object]:
        if not self.path.exists():
            return {
                "version": CHECKPOINT_VERSION,
                "source": SOURCE,
                "historical_start": format_utc_hour(self.historical_start),
                "historical_cutoff": format_utc_hour(self.historical_cutoff),
                "hours": {},
            }
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CheckpointError(f"cannot read checkpoint: {self.path}") from exc
        if not isinstance(loaded, dict):
            raise CheckpointError("checkpoint root must be an object")
        if loaded.get("version") != CHECKPOINT_VERSION:
            raise CheckpointError("unsupported checkpoint version")
        if loaded.get("source") != SOURCE:
            raise CheckpointError("checkpoint source does not match gharchive")
        if loaded.get("historical_start") != format_utc_hour(self.historical_start):
            raise CheckpointError("checkpoint historical_start does not match")
        if loaded.get("historical_cutoff") != format_utc_hour(self.historical_cutoff):
            raise CheckpointError("checkpoint historical_cutoff does not match")
        if not isinstance(loaded.get("hours"), dict):
            raise CheckpointError("checkpoint hours must be an object")
        return loaded

    @property
    def hours(self) -> dict[str, object]:
        return self.data["hours"]  # type: ignore[return-value]

    def record(self, hour: datetime) -> Mapping[str, object] | None:
        value = self.hours.get(format_utc_hour(hour))
        return value if isinstance(value, dict) else None

    def record_complete(
        self,
        archive: ArchiveFile,
        validation: FileValidation,
        *,
        location: str,
        attempts: int,
    ) -> None:
        self.hours[format_utc_hour(archive.hour)] = {
            "status": "complete",
            "source_url": archive.url,
            "filename": archive.filename,
            "location": location,
            "compressed_bytes": validation.compressed_bytes,
            "uncompressed_bytes": validation.uncompressed_bytes,
            "sha256": validation.sha256,
            "gzip_valid": True,
            "attempts": attempts,
            "error": None,
            "completed_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        }
        self._save()

    def record_failure(
        self,
        archive: ArchiveFile,
        *,
        attempts: int,
        error: str,
    ) -> None:
        self.hours[format_utc_hour(archive.hour)] = {
            "status": "failed",
            "source_url": archive.url,
            "filename": archive.filename,
            "attempts": attempts,
            "error": error,
            "completed_at": None,
        }
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f"{self.path.name}.tmp")
        with temporary_path.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(self.data, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, self.path)


@dataclass(frozen=True)
class _HourResult:
    status: str
    validation: FileValidation | None
    error: str | None = None


class HistoricalDownloader:
    """Download a bounded sequence of hourly Raw archives with resume safety."""

    def __init__(
        self,
        output_root: Path = DEFAULT_OUTPUT_ROOT,
        *,
        checkpoint_path: Path | None = None,
        transport: HttpTransport | None = None,
        timeout: float = 30.0,
        max_attempts: int = 3,
        backoff_seconds: float = 1.0,
        chunk_size: int = CHUNK_SIZE,
        sleep: Callable[[float], None] = time.sleep,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds cannot be negative")
        if chunk_size < 1:
            raise ValueError("chunk_size must be at least 1")

        self.output_root = output_root.resolve()
        self.checkpoint_path = (
            checkpoint_path.resolve()
            if checkpoint_path is not None
            else self.output_root / "checkpoint.json"
        )
        self.transport = transport or UrllibTransport()
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.chunk_size = chunk_size
        self.sleep = sleep
        self.base_url = base_url

    def download(
        self,
        start: datetime,
        end: datetime,
        *,
        historical_start: datetime = HISTORICAL_START,
        historical_cutoff: datetime = HISTORICAL_CUTOFF,
    ) -> DownloadSummary:
        archives = expected_archives(
            start,
            end,
            historical_start=historical_start,
            historical_cutoff=historical_cutoff,
            base_url=self.base_url,
        )
        checkpoint = CheckpointStore(
            self.checkpoint_path,
            historical_start=historical_start,
            historical_cutoff=historical_cutoff,
        )
        downloaded: list[str] = []
        reused: list[str] = []
        failed: dict[str, str] = {}
        completed: set[str] = set()
        downloaded_bytes = 0
        uncompressed_bytes = 0

        for archive in archives:
            result = self._ensure_archive(archive, checkpoint)
            hour_key = format_utc_hour(archive.hour)
            if result.status == "downloaded":
                downloaded.append(hour_key)
            elif result.status == "reused":
                reused.append(hour_key)
            else:
                failed[hour_key] = result.error or "unknown download failure"
                continue

            completed.add(hour_key)
            if result.validation is not None:
                uncompressed_bytes += result.validation.uncompressed_bytes
                if result.status == "downloaded":
                    downloaded_bytes += result.validation.compressed_bytes

        expected_hours = tuple(format_utc_hour(item.hour) for item in archives)
        missing = tuple(hour for hour in expected_hours if hour not in completed)
        return DownloadSummary(
            expected=len(archives),
            downloaded=tuple(downloaded),
            reused=tuple(reused),
            failed=failed,
            missing=missing,
            downloaded_bytes=downloaded_bytes,
            validated_uncompressed_bytes=uncompressed_bytes,
        )

    def _ensure_archive(
        self,
        archive: ArchiveFile,
        checkpoint: CheckpointStore,
    ) -> _HourResult:
        final_path = archive.final_path(self.output_root)
        existing_record = checkpoint.record(archive.hour)
        validation = self._validated_reusable_file(final_path, existing_record)
        prior_attempts = _checkpoint_attempts(existing_record)
        if validation is not None:
            checkpoint.record_complete(
                archive,
                validation,
                location=archive.relative_path.as_posix(),
                attempts=prior_attempts,
            )
            return _HourResult("reused", validation)

        part_path = archive.partial_path(self.output_root)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        attempts = prior_attempts
        last_error = "download did not start"

        for attempt_index in range(self.max_attempts):
            attempts += 1
            part_path.unlink(missing_ok=True)
            try:
                validation = self._download_once(archive, part_path, final_path)
            except (KeyboardInterrupt, InterruptedError):
                raise
            except Exception as exc:  # noqa: BLE001 - persisted and classified below
                last_error = f"{type(exc).__name__}: {exc}"
                if (
                    not self._is_retryable(exc)
                    or attempt_index + 1 >= self.max_attempts
                ):
                    break
                self.sleep(self.backoff_seconds * (2**attempt_index))
                continue

            checkpoint.record_complete(
                archive,
                validation,
                location=archive.relative_path.as_posix(),
                attempts=attempts,
            )
            return _HourResult("downloaded", validation)

        checkpoint.record_failure(archive, attempts=attempts, error=last_error)
        return _HourResult("failed", None, last_error)

    def _validated_reusable_file(
        self,
        final_path: Path,
        checkpoint_record: Mapping[str, object] | None,
    ) -> FileValidation | None:
        if not final_path.is_file():
            return None
        try:
            validation = validate_gzip_file(final_path)
        except ArchiveValidationError:
            return None

        if checkpoint_record and checkpoint_record.get("status") == "complete":
            if checkpoint_record.get("compressed_bytes") != validation.compressed_bytes:
                return None
            if checkpoint_record.get("sha256") != validation.sha256:
                return None
        return validation

    def _download_once(
        self,
        archive: ArchiveFile,
        part_path: Path,
        final_path: Path,
    ) -> FileValidation:
        response = self.transport.open(archive.url, self.timeout)
        try:
            status = getattr(response, "status", 200)
            if status != 200:
                raise HttpStatusError(status, archive.url)
            expected_length = _content_length(response.headers)
            written = 0
            with part_path.open("wb") as stream:
                while chunk := response.read(self.chunk_size):
                    stream.write(chunk)
                    written += len(chunk)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            response.close()

        if expected_length is not None and written != expected_length:
            raise ArchiveValidationError(
                f"Content-Length mismatch for {archive.filename}: "
                f"expected {expected_length}, wrote {written}"
            )

        validation = validate_gzip_file(part_path)
        if validation.compressed_bytes != written:
            raise ArchiveValidationError(
                f"written byte count changed before validation: {archive.filename}"
            )
        os.replace(part_path, final_path)
        return validation

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, urllib.error.HTTPError):
            return exc.code == 429 or 500 <= exc.code < 600
        if isinstance(exc, HttpStatusError):
            return exc.status == 429 or 500 <= exc.status < 600
        return isinstance(
            exc,
            (
                ArchiveValidationError,
                ConnectionError,
                TimeoutError,
                urllib.error.URLError,
            ),
        )


def validate_downloaded_range(
    output_root: Path,
    start: datetime,
    end: datetime,
    *,
    historical_start: datetime = HISTORICAL_START,
    historical_cutoff: datetime = HISTORICAL_CUTOFF,
    base_url: str = DEFAULT_BASE_URL,
) -> ValidationSummary:
    archives = expected_archives(
        start,
        end,
        historical_start=historical_start,
        historical_cutoff=historical_cutoff,
        base_url=base_url,
    )
    completed: list[str] = []
    missing: list[str] = []
    invalid: dict[str, str] = {}
    compressed_bytes = 0
    uncompressed_bytes = 0

    for archive in archives:
        hour_key = format_utc_hour(archive.hour)
        path = archive.final_path(output_root.resolve())
        if not path.is_file():
            missing.append(hour_key)
            continue
        try:
            validation = validate_gzip_file(path)
        except ArchiveValidationError as exc:
            invalid[hour_key] = str(exc)
            continue
        completed.append(hour_key)
        compressed_bytes += validation.compressed_bytes
        uncompressed_bytes += validation.uncompressed_bytes

    return ValidationSummary(
        expected=len(archives),
        completed=tuple(completed),
        missing=tuple(missing),
        invalid=invalid,
        compressed_bytes=compressed_bytes,
        uncompressed_bytes=uncompressed_bytes,
    )


def _checkpoint_attempts(record: Mapping[str, object] | None) -> int:
    if record is None:
        return 0
    attempts = record.get("attempts", 0)
    return attempts if isinstance(attempts, int) and attempts >= 0 else 0


def _content_length(headers: Mapping[str, str]) -> int | None:
    value = headers.get("Content-Length")
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ArchiveValidationError("Content-Length is not an integer") from exc
    if parsed < 0:
        raise ArchiveValidationError("Content-Length cannot be negative")
    return parsed
