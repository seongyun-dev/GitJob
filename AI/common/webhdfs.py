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


def parse_datanode_hosts(value: str | None) -> dict[str, str]:
    """Parse `WEBHDFS_DATANODE_HOSTS` into a redirect rewrite table.

    ### Why a rewrite table exists

    A WebHDFS read or write is two hops: the NameNode answers `307` and the
    bytes move against the `Location` it names. That `Location` carries the
    DataNode's *own* advertised hostname — inside the operational cluster
    `http://hdfs-datanode3:9864/...` — and Hadoop offers no way to make it
    anything else per client.

    In the container the name resolves and nothing here is needed. From
    outside the Compose network it does not, so a run collects and then
    silently keeps its files locally, which is the failure S15P21E102-189 and
    `docs/data/README.md` §14.1 record. Rewriting the redirect target is what
    lets a caller off the cluster network finish the second hop.

    Format is `container-host:port=reachable-host:port`, comma separated:

        hdfs-datanode:9864=100.70.66.38:9864,hdfs-datanode2:9864=100.70.66.38:9866

    The ports differ on the right because all three DataNodes serve `9864`
    inside the network and `compose.ec2-data.yaml` publishes them on distinct
    host ports. Unset means no rewriting — the in-cluster default.
    """

    table: dict[str, str] = {}
    for entry in (value or "").split(","):
        item = entry.strip()
        if not item:
            continue
        source, separator, target = item.partition("=")
        source, target = source.strip(), target.strip()
        if not separator or not source or not target:
            raise ValueError(
                "WebHDFS datanode host map entries must be "
                f"'host:port=host:port', got {item!r}"
            )
        table[source] = target
    return table


def rewrite_datanode_host(location: str, table: Mapping[str, str]) -> str:
    """Point a `307` `Location` at a host the caller can actually reach.

    An empty table returns the location untouched — the in-cluster default,
    where the DataNode name already resolves.

    An unmapped host raises rather than being followed as-is. A configured
    table means the caller is off the cluster network, so an unlisted DataNode
    — a fourth one added on the server, say — cannot resolve either. Failing
    here names the missing entry; following the URL would spend the whole
    timeout in DNS and report only a bare connection error.
    """

    if not table:
        return location
    parsed = urllib.parse.urlsplit(location)
    replacement = table.get(parsed.netloc) or table.get(parsed.hostname or "")
    if replacement is None:
        raise WebHdfsError(
            f"WebHDFS redirected to {parsed.netloc!r}, which is absent from the "
            "DataNode host map (WEBHDFS_DATANODE_HOSTS) and is not reachable "
            "from here"
        )
    return urllib.parse.urlunsplit(parsed._replace(netloc=replacement))


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


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Surface WebHDFS redirects instead of letting urllib chase them.

    urllib follows a `307` on GET by itself but not on PUT, so `OPEN` used to
    take a hidden path that `CREATE` never did. That asymmetry hid a bug: the
    second hop names a DataNode by its container hostname, and a silent follow
    skips `rewrite_datanode_host`, so from off the cluster network a write
    succeeded while a read failed DNS. Both verbs now come back as a `307`
    that `WebHdfsClient` follows deliberately.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# One opener, built once: `urlopen` installs the redirect-following default.
_OPENER = urllib.request.build_opener(_NoRedirectHandler)


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
            with _OPENER.open(request, timeout=timeout) as response:
                return WebHdfsResponse(
                    status=int(response.status),
                    headers=dict(response.headers),
                    body=response.read(),
                )
        except urllib.error.HTTPError as exc:
            # OPEN and CREATE both return 307; the Location is handled
            # explicitly by the caller, never by urllib.
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
    # `container-host:port` -> `reachable-host:port` for the `307` second hop.
    # Empty is the in-cluster default; see `parse_datanode_hosts`.
    datanode_hosts: Mapping[str, str] = field(default_factory=dict)

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

    def _redirect_target(self, location: str) -> str:
        return rewrite_datanode_host(location, self.datanode_hosts)

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
            response = self.transport.request(
                "GET", self._redirect_target(location), timeout=self.timeout
            )
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
            "PUT",
            self._redirect_target(location),
            body=content,
            timeout=self.timeout,
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
