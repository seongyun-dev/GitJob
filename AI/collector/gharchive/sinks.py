"""Raw sink boundaries for validated GH Archive files.

Two adapters publish the same logical Raw layout:

- :class:`WebHdfsSink` talks to the NameNode WebHDFS HTTP API. This is the
  deployed default because the collector/worker image is a slim Python runtime
  with neither a Hadoop CLI nor a JRE.
- :class:`HdfsCliSink` shells out to ``hdfs dfs``. It is kept for execution
  contexts that do provide the Hadoop CLI.

Both preserve the downloaded bytes unchanged, publish through a temporary path
so an interrupted transfer never becomes a final object, and never overwrite an
existing final object.
"""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Protocol

from collector.gharchive.historical import (
    ArchiveValidationError,
    RangeValidationError,
    expected_archives,
    format_utc_hour,
    validate_gzip_file,
)

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class RawSink(Protocol):
    """Publish one validated Raw object and report whether it is already there."""

    def exists(self, hour: datetime, filename: str) -> bool: ...

    def store(self, local_path: Path, hour: datetime) -> str: ...


class HdfsSinkError(RuntimeError):
    """Raised when an HDFS CLI operation cannot preserve a Raw object."""


DEFAULT_RAW_ROOT = "/gitjob/raw"
"""Canonical Raw root.

The first HDFS path segment is the environment namespace: ``.env.example`` uses
``gitjob`` and ``.env.ci.example`` uses ``gitjob-ci`` for the same
``PARQUET_ROOT`` setting, and ``Infra/compose/compose.yaml`` creates and chowns
``/gitjob`` separately from ``/gitjob/parquet``. Raw therefore belongs under the
same namespace root as Parquet, not at the filesystem root.
"""


def hdfs_raw_path(
    hour: datetime,
    filename: str,
    *,
    raw_root: str = DEFAULT_RAW_ROOT,
    source: str = "gharchive",
) -> PurePosixPath:
    if hour.tzinfo is None:
        raise RangeValidationError("HDFS Raw hour must include a timezone")
    hour = hour.astimezone(UTC)
    if any((hour.minute, hour.second, hour.microsecond)):
        raise RangeValidationError("HDFS Raw hour must be aligned to an hour")
    if PurePosixPath(filename).name != filename or filename in {"", ".", ".."}:
        raise ValueError("filename must be a single path component")
    return _raw_root_path(raw_root) / source / f"dt={hour:%Y-%m-%d}" / filename


def _raw_root_path(raw_root: str) -> PurePosixPath:
    """Accept a bare path or an ``hdfs://`` URI, matching ``PARQUET_ROOT``.

    ``.env`` declares Parquet as ``hdfs:///gitjob/parquet``, so ``RAW_ROOT`` may
    be given the same way. Only the path component is used; the endpoint comes
    from the WebHDFS base URL or the Hadoop configuration.
    """

    candidate = raw_root.strip()
    if "://" in candidate:
        parsed = urllib.parse.urlsplit(candidate)
        if parsed.scheme != "hdfs":
            raise ValueError("raw_root URI must use the hdfs scheme")
        candidate = parsed.path
    candidate = candidate.strip("/")
    if not candidate:
        raise ValueError("raw_root must not be empty")
    return PurePosixPath("/") / candidate


@dataclass
class HdfsCliSink:
    """Optional Hadoop CLI adapter; the current runtime does not provide it."""

    raw_root: str = DEFAULT_RAW_ROOT
    source: str = "gharchive"
    runner: CommandRunner | None = None

    def exists(self, hour: datetime, filename: str) -> bool:
        runner = self.runner or _run_command
        destination = hdfs_raw_path(
            hour,
            filename,
            raw_root=self.raw_root,
            source=self.source,
        )
        result = runner(("hdfs", "dfs", "-test", "-e", destination.as_posix()))
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        raise _command_error("test destination", result)

    def store(self, local_path: Path, hour: datetime) -> str:
        if not local_path.is_file():
            raise HdfsSinkError(f"local Raw file is missing: {local_path}")
        runner = self.runner or _run_command
        destination = hdfs_raw_path(
            hour,
            local_path.name,
            raw_root=self.raw_root,
            source=self.source,
        )
        destination_text = destination.as_posix()
        if self.exists(hour, local_path.name):
            return f"hdfs://{destination_text}"

        directory = destination.parent.as_posix()
        _require_success(
            "create Raw partition",
            runner(("hdfs", "dfs", "-mkdir", "-p", directory)),
        )
        temporary = f"{destination_text}.uploading-{uuid.uuid4().hex}"
        try:
            _require_success(
                "upload temporary Raw file",
                runner(("hdfs", "dfs", "-put", str(local_path), temporary)),
            )
            _require_success(
                "publish Raw file",
                runner(("hdfs", "dfs", "-mv", temporary, destination_text)),
            )
        except HdfsSinkError:
            # 실패한 시도가 임시 파일을 HDFS 에 남기지 않도록 정리한다.
            # 이미 publish 된 뒤라면 temporary 가 없으므로 -f 로 무시된다.
            runner(("hdfs", "dfs", "-rm", "-f", "-skipTrash", temporary))
            raise
        return f"hdfs://{destination_text}"


DEFAULT_WEBHDFS_USER = "hadoop"
_WEBHDFS_OK = (200, 201)


@dataclass(frozen=True)
class WebHdfsResponse:
    """One WebHDFS HTTP response. Error statuses are returned, not raised."""

    status: int
    headers: Mapping[str, str]
    body: bytes


class WebHdfsTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        body: Path | None = None,
        timeout: float,
    ) -> WebHdfsResponse: ...


class UrllibWebHdfsTransport:
    """Small stdlib transport so runtime dependencies stay unchanged."""

    def request(
        self,
        method: str,
        url: str,
        *,
        body: Path | None = None,
        timeout: float,
    ) -> WebHdfsResponse:
        headers: dict[str, str] = {}
        stream = None
        if body is not None:
            headers["Content-Length"] = str(body.stat().st_size)
            headers["Content-Type"] = "application/octet-stream"
            stream = body.open("rb")
        request = urllib.request.Request(
            url,
            data=stream,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self._positive(timeout)
            ) as response:
                return WebHdfsResponse(
                    status=response.status,
                    headers=dict(response.headers),
                    body=response.read(),
                )
        except urllib.error.HTTPError as exc:
            # WebHDFS answers CREATE with 307 and urllib does not follow a
            # redirect for PUT, so the status is classified by the caller.
            with exc:
                return WebHdfsResponse(
                    status=exc.code,
                    headers=dict(exc.headers),
                    body=exc.read(),
                )
        except urllib.error.URLError as exc:
            raise HdfsSinkError(f"WebHDFS request failed: {exc.reason}") from exc
        finally:
            if stream is not None:
                stream.close()

    @staticmethod
    def _positive(timeout: float) -> float:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        return timeout


@dataclass
class WebHdfsSink:
    """Publish a validated Raw file through the NameNode WebHDFS HTTP API.

    ``base_url`` is the WebHDFS API base including the version prefix, for
    example ``http://hdfs-namenode:9870/webhdfs/v1``. No Hadoop CLI, JRE, or
    extra Python dependency is required.
    """

    base_url: str
    raw_root: str = DEFAULT_RAW_ROOT
    source: str = "gharchive"
    user: str = DEFAULT_WEBHDFS_USER
    timeout: float = 120.0
    transport: WebHdfsTransport = field(default_factory=UrllibWebHdfsTransport)

    def __post_init__(self) -> None:
        base = self.base_url.strip()
        if not base:
            raise ValueError("WebHDFS base_url must not be empty")
        parsed = urllib.parse.urlsplit(base)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("WebHDFS base_url must be an http or https URL")
        if parsed.query or parsed.fragment:
            raise ValueError("WebHDFS base_url must not carry a query or fragment")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        self.base_url = base.rstrip("/")

    def exists(self, hour: datetime, filename: str) -> bool:
        return self._exists(self._destination(hour, filename).as_posix())

    def store(self, local_path: Path, hour: datetime) -> str:
        """Return the published ``hdfs://`` location, uploading only if absent."""

        if not local_path.is_file():
            raise HdfsSinkError(f"local Raw file is missing: {local_path}")
        destination = self._destination(hour, local_path.name)
        destination_text = destination.as_posix()
        location = f"hdfs://{destination_text}"
        if self._exists(destination_text):
            return location

        self._make_directory(destination.parent.as_posix())
        temporary = f"{destination_text}.uploading-{uuid.uuid4().hex}"
        try:
            self._upload(temporary, local_path)
            self._publish(temporary, destination_text)
        except HdfsSinkError:
            # A failed attempt must not leave an .uploading- object behind.
            self._discard(temporary)
            raise
        return location

    def _destination(self, hour: datetime, filename: str) -> PurePosixPath:
        return hdfs_raw_path(
            hour,
            filename,
            raw_root=self.raw_root,
            source=self.source,
        )

    def _exists(self, path: str) -> bool:
        response = self._call("GET", path, "GETFILESTATUS")
        if response.status == 200:
            return True
        if response.status == 404:
            return False
        raise _webhdfs_error("check destination", response)

    def _make_directory(self, path: str) -> None:
        response = self._call("PUT", path, "MKDIRS")
        if response.status not in _WEBHDFS_OK or not _boolean_result(response):
            raise _webhdfs_error("create Raw partition", response)

    def _upload(self, path: str, local_path: Path) -> None:
        redirect = self._call("PUT", path, "CREATE", overwrite="false")
        if redirect.status != 307:
            raise _webhdfs_error("open temporary Raw file", redirect)
        target = redirect.headers.get("Location")
        if not target:
            raise HdfsSinkError("WebHDFS CREATE returned no redirect Location")
        written = self.transport.request(
            "PUT",
            target,
            body=local_path,
            timeout=self.timeout,
        )
        if written.status != 201:
            raise _webhdfs_error("upload temporary Raw file", written)

    def _publish(self, temporary: str, destination: str) -> None:
        # HDFS RENAME reports false instead of overwriting an existing object,
        # so an already-published hour is never replaced by a later attempt.
        response = self._call("PUT", temporary, "RENAME", destination=destination)
        if response.status not in _WEBHDFS_OK or not _boolean_result(response):
            raise _webhdfs_error("publish Raw file", response)

    def _discard(self, path: str) -> None:
        try:
            self._call("DELETE", path, "DELETE")
        except (HdfsSinkError, OSError):
            # Cleanup is best effort and must not mask the original failure.
            pass

    def _call(
        self,
        method: str,
        path: str,
        operation: str,
        **parameters: str,
    ) -> WebHdfsResponse:
        query = urllib.parse.urlencode(
            {"op": operation, "user.name": self.user, **parameters}
        )
        quoted = urllib.parse.quote(path, safe="/=")
        return self.transport.request(
            method,
            f"{self.base_url}{quoted}?{query}",
            timeout=self.timeout,
        )


def _boolean_result(response: WebHdfsResponse) -> bool:
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("boolean") is True


def _webhdfs_error(action: str, response: WebHdfsResponse) -> HdfsSinkError:
    body = response.body.decode("utf-8", "replace").strip()
    detail = body[:300] or "no response body"
    return HdfsSinkError(f"failed to {action} (HTTP {response.status}): {detail}")


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise HdfsSinkError("hdfs CLI is not available") from exc


def _require_success(
    action: str,
    result: subprocess.CompletedProcess[str],
) -> None:
    if result.returncode != 0:
        raise _command_error(action, result)


def _command_error(
    action: str,
    result: subprocess.CompletedProcess[str],
) -> HdfsSinkError:
    detail = (result.stderr or result.stdout or "no command output").strip()
    return HdfsSinkError(f"failed to {action} (exit={result.returncode}): {detail}")


@dataclass(frozen=True)
class PublishSummary:
    """Per-hour result of publishing a downloaded range into HDFS Raw.

    ``missing`` is an hour with no local file, ``invalid`` is a local file that
    fails gzip validation, and ``failed`` is a sink error. The four result sets
    never overlap, so
    ``expected == len(uploaded) + len(reused) + len(missing) + len(invalid) + len(failed)``.
    """

    expected: int
    uploaded: tuple[str, ...]
    reused: tuple[str, ...]
    missing: tuple[str, ...]
    invalid: Mapping[str, str]
    failed: Mapping[str, str]
    published_bytes: int

    def as_dict(self) -> dict[str, object]:
        return {
            "expected": self.expected,
            "uploaded": len(self.uploaded),
            "reused": len(self.reused),
            "missing": len(self.missing),
            "invalid": len(self.invalid),
            "failed": len(self.failed),
            "uploaded_hours": list(self.uploaded),
            "reused_hours": list(self.reused),
            "missing_hours": list(self.missing),
            "invalid_archives": dict(self.invalid),
            "failures": dict(self.failed),
            "published_bytes": self.published_bytes,
        }


def publish_downloaded_range(
    sink: RawSink,
    output_root: Path,
    start: datetime,
    end: datetime,
    *,
    historical_start: datetime | None = None,
    historical_cutoff: datetime | None = None,
    archive_base_url: str | None = None,
) -> PublishSummary:
    """Publish locally validated hourly archives, skipping hours already in HDFS.

    Only files that pass gzip validation are handed to the sink, so a partial or
    corrupt local download is never published. Hours already present in HDFS are
    reported as reused without being decompressed again.
    """

    keywords: dict[str, object] = {}
    if historical_start is not None:
        keywords["historical_start"] = historical_start
    if historical_cutoff is not None:
        keywords["historical_cutoff"] = historical_cutoff
    if archive_base_url is not None:
        keywords["base_url"] = archive_base_url
    archives = expected_archives(start, end, **keywords)  # type: ignore[arg-type]

    root = output_root.resolve()
    uploaded: list[str] = []
    reused: list[str] = []
    missing: list[str] = []
    invalid: dict[str, str] = {}
    failed: dict[str, str] = {}
    published_bytes = 0

    for archive in archives:
        hour_key = format_utc_hour(archive.hour)
        local_path = archive.final_path(root)
        if not local_path.is_file():
            missing.append(hour_key)
            continue
        try:
            # Existence is checked before gzip validation so a re-run does not
            # decompress hours that are already published.
            if sink.exists(archive.hour, archive.filename):
                reused.append(hour_key)
                continue
        except HdfsSinkError as exc:
            failed[hour_key] = str(exc)
            continue
        try:
            validation = validate_gzip_file(local_path)
        except ArchiveValidationError as exc:
            invalid[hour_key] = str(exc)
            continue
        try:
            sink.store(local_path, archive.hour)
        except HdfsSinkError as exc:
            failed[hour_key] = str(exc)
            continue
        uploaded.append(hour_key)
        published_bytes += validation.compressed_bytes

    return PublishSummary(
        expected=len(archives),
        uploaded=tuple(uploaded),
        reused=tuple(reused),
        missing=tuple(missing),
        invalid=invalid,
        failed=failed,
        published_bytes=published_bytes,
    )
