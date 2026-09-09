"""Dependency-free WebHDFS transport and immutable object operations."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol


class WebHdfsError(RuntimeError):
    """Raised when WebHDFS cannot preserve an immutable object."""


@dataclass(frozen=True)
class WebHdfsResponse:
    """One WebHDFS HTTP response. HTTP error statuses are not raised."""

    status: int
    headers: Mapping[str, str]
    body: bytes


class WebHdfsTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        body: Path | bytes | None = None,
        timeout: float,
    ) -> WebHdfsResponse: ...


class UrllibWebHdfsTransport:
    """Small stdlib transport suitable for the slim collector/worker image."""

    def request(
        self,
        method: str,
        url: str,
        *,
        body: Path | bytes | None = None,
        timeout: float,
    ) -> WebHdfsResponse:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        headers: dict[str, str] = {}
        stream = None
        request_body = None
        if isinstance(body, Path):
            headers["Content-Length"] = str(body.stat().st_size)
            headers["Content-Type"] = "application/octet-stream"
            stream = body.open("rb")
            request_body = stream
        elif body is not None:
            headers["Content-Length"] = str(len(body))
            headers["Content-Type"] = "application/octet-stream"
            request_body = body
        request = urllib.request.Request(
            url,
            data=request_body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return WebHdfsResponse(
                    status=int(response.status),
                    headers=dict(response.headers),
                    body=response.read(),
                )
        except urllib.error.HTTPError as exc:
            # CREATE returns 307 for PUT; its Location is handled explicitly.
            with exc:
                return WebHdfsResponse(
                    status=int(exc.code),
                    headers=dict(exc.headers) if exc.headers else {},
                    body=exc.read(),
                )
        except urllib.error.URLError as exc:
            raise WebHdfsError(f"WebHDFS request failed: {exc.reason}") from exc
        finally:
            if stream is not None:
                stream.close()


@dataclass
class WebHdfsClient:
    """Generic immutable byte-object client over the WebHDFS HTTP API."""

    base_url: str
    user: str = "hadoop"
    timeout: float = 120.0
    transport: WebHdfsTransport = field(default_factory=UrllibWebHdfsTransport)

    def __post_init__(self) -> None:
        base = self.base_url.strip()
        parsed = urllib.parse.urlsplit(base)
        if not base or parsed.scheme not in {"http", "https"}:
            raise ValueError("WebHDFS base_url must be an http or https URL")
        if parsed.query or parsed.fragment:
            raise ValueError("WebHDFS base_url must not carry a query or fragment")
        if not self.user.strip():
            raise ValueError("WebHDFS user must not be blank")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        self.base_url = base.rstrip("/")

    def exists(self, path: str | PurePosixPath) -> bool:
        response = self._call("GET", path, "GETFILESTATUS")
        if response.status == 200:
            return True
        if response.status == 404:
            return False
        raise self._error("check object", response)

    def length(self, path: str | PurePosixPath) -> int | None:
        """Byte length of an object, or `None` when it is absent.

        Added for `job.collector.raw_verify`: checking existence alone would
        pass a truncated upload, and reading a 34 MB batch back to compare
        bytes costs more than the check is worth. `GETFILESTATUS` returns the
        length in the same request that answers existence.
        """

        response = self._call("GET", path, "GETFILESTATUS")
        if response.status == 404:
            return None
        if response.status != 200:
            raise self._error("read object status", response)
        try:
            payload = json.loads(response.body.decode("utf-8"))
            return int(payload["FileStatus"]["length"])
        except (ValueError, KeyError, TypeError) as error:
            raise WebHdfsError(
                f"GETFILESTATUS returned an unexpected shape: {error}"
            ) from error

    def read(self, path: str | PurePosixPath) -> bytes:
        response = self._call("GET", path, "OPEN")
        if response.status == 307:
            location = _header(response.headers, "Location")
            if not location:
                raise WebHdfsError("WebHDFS OPEN returned no redirect Location")
            response = self.transport.request("GET", location, timeout=self.timeout)
        if response.status != 200:
            raise self._error("read object", response)
        return response.body

    def store_immutable(
        self,
        path: str | PurePosixPath,
        content: bytes,
    ) -> str:
        destination = normalize_hdfs_path(path).as_posix()
        if self.exists(destination):
            if self.read(destination) != content:
                raise FileExistsError(
                    "immutable WebHDFS object exists with different content"
                )
            return hdfs_uri(destination)

        self._mkdirs(PurePosixPath(destination).parent)
        temporary = f"{destination}.uploading-{uuid.uuid4().hex}"
        try:
            self._create(temporary, content)
            renamed = self._call("PUT", temporary, "RENAME", destination=destination)
            if renamed.status not in {200, 201} or not _boolean_result(renamed):
                # A concurrent immutable writer may have won the race.
                if self.exists(destination) and self.read(destination) == content:
                    self._discard(temporary)
                    return hdfs_uri(destination)
                raise self._error("publish object", renamed)
        except (OSError, WebHdfsError):
            self._discard(temporary)
            raise
        return hdfs_uri(destination)

    def _mkdirs(self, path: str | PurePosixPath) -> None:
        response = self._call("PUT", path, "MKDIRS")
        if response.status not in {200, 201} or not _boolean_result(response):
            raise self._error("create object directory", response)

    def _create(self, path: str, content: bytes) -> None:
        redirect = self._call("PUT", path, "CREATE", overwrite="false")
        if redirect.status != 307:
            raise self._error("open temporary object", redirect)
        location = _header(redirect.headers, "Location")
        if not location:
            raise WebHdfsError("WebHDFS CREATE returned no redirect Location")
        written = self.transport.request(
            "PUT", location, body=content, timeout=self.timeout
        )
        if written.status != 201:
            raise self._error("upload temporary object", written)

    def _discard(self, path: str) -> None:
        try:
            self._call("DELETE", path, "DELETE")
        except (OSError, WebHdfsError):
            pass

    def _call(
        self,
        method: str,
        path: str | PurePosixPath,
        operation: str,
        **parameters: str,
    ) -> WebHdfsResponse:
        normalized = normalize_hdfs_path(path).as_posix()
        query = urllib.parse.urlencode(
            {"op": operation, "user.name": self.user, **parameters}
        )
        quoted = urllib.parse.quote(normalized, safe="/=")
        return self.transport.request(
            method,
            f"{self.base_url}{quoted}?{query}",
            timeout=self.timeout,
        )

    @staticmethod
    def _error(action: str, response: WebHdfsResponse) -> WebHdfsError:
        body = response.body.decode("utf-8", "replace").strip()
        detail = body[:300] or "no response body"
        return WebHdfsError(f"failed to {action} (HTTP {response.status}): {detail}")


def normalize_hdfs_path(value: str | PurePosixPath) -> PurePosixPath:
    candidate = str(value).strip()
    if "://" in candidate:
        parsed = urllib.parse.urlsplit(candidate)
        if parsed.scheme != "hdfs" or parsed.query or parsed.fragment:
            raise ValueError("HDFS URI must use the hdfs scheme without query")
        candidate = parsed.path
    if not candidate.startswith("/"):
        raise ValueError("HDFS path must be absolute")
    if any(part in {".", ".."} for part in candidate.split("/")):
        raise ValueError("HDFS path must not contain traversal segments")
    path = PurePosixPath(candidate)
    return path


def hdfs_uri(path: str | PurePosixPath) -> str:
    return f"hdfs://{normalize_hdfs_path(path).as_posix()}"


def _boolean_result(response: WebHdfsResponse) -> bool:
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("boolean") is True


def _header(headers: Mapping[str, str], name: str) -> str | None:
    lowered = name.casefold()
    return next(
        (value for key, value in headers.items() if key.casefold() == lowered),
        None,
    )
