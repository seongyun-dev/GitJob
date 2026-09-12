"""Read-only WebHDFS input with byte, namespace and redirect authority bounds."""

import json
import math
import threading
import time
from collections.abc import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from common.webhdfs import WebHdfsError


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(c.isspace() for c in value)
    ):
        raise ValueError("an explicit HTTP(S) origin without credentials is required")
    _ = parsed.port
    return f"{parsed.scheme}://{parsed.netloc}"


def _path(value: str) -> str:
    decoded = unquote(value, errors="strict")
    if (
        not decoded.startswith("/")
        or "%" in decoded
        or "\\" in decoded
        or any(ord(c) < 32 or ord(c) == 127 for c in decoded)
        or any(part in {"", ".", ".."} for part in decoded[1:].split("/"))
    ):
        raise ValueError("unsafe HDFS path")
    return decoded


class ReadOnlyWebHdfsReader:
    """GET-only reader configured by an operator, never by an event payload.

    Routes map advertised DataNode origins to explicitly reachable origins.
    No ambient proxies, credential forwarding or arbitrary redirects are used.
    """

    def __init__(
        self,
        base_url: str,
        uri_prefix: str,
        *,
        datanode_routes: Mapping[str, str] | None = None,
        user: str = "hadoop",
        timeout: float = 15,
        max_attempts: int = 3,
        max_requests: int = 50_000,
        max_response_bytes: int = 64 * 1024 * 1024,
        opener=None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        origin = _http_origin(base_url)
        parsed = urlsplit(base_url)
        if parsed.path.rstrip("/") != "/webhdfs/v1":
            raise ValueError("WebHDFS base URL must end in /webhdfs/v1")
        prefix = urlsplit(uri_prefix.rstrip("/"))
        if prefix.scheme != "hdfs" or prefix.query or prefix.fragment:
            raise ValueError("a fixed HDFS URI namespace is required")
        self._prefix_path = _path(prefix.path)
        self._prefix_authority = prefix.netloc
        if not user or any(ord(c) < 33 for c in user):
            raise ValueError("invalid HDFS user")
        if not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValueError("timeout must be in (0, 60]")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        if type(max_requests) is not int or max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if (
            type(max_response_bytes) is not int
            or not 1 <= max_response_bytes <= 256 * 1024 * 1024
        ):
            raise ValueError("response byte bound must be within 256 MiB")
        self._routes = {origin: origin}
        for advertised, reachable in (datanode_routes or {}).items():
            if urlsplit(advertised).path not in {"", "/"} or urlsplit(
                reachable
            ).path not in {"", "/"}:
                raise ValueError("DataNode routes must contain origins only")
            self._routes[_http_origin(advertised)] = _http_origin(reachable)
        self._base_url = base_url.rstrip("/")
        self._user = user
        self._timeout = timeout
        self._attempts = max_attempts
        self._max_requests = max_requests
        self._max_bytes = max_response_bytes
        self._opener = opener or build_opener(ProxyHandler({}), _NoRedirect())
        self._sleep = sleep
        self._lock = threading.Lock()
        self.stats = {"requests": 0, "retries": 0, "bytes_read": 0}

    def _uri_path(self, uri: str) -> str:
        parsed = urlsplit(uri)
        path = _path(parsed.path)
        if (
            parsed.scheme != "hdfs"
            or parsed.netloc != self._prefix_authority
            or parsed.query
            or parsed.fragment
            or not (
                path == self._prefix_path or path.startswith(self._prefix_path + "/")
            )
        ):
            raise ValueError("URI is outside the configured HDFS namespace")
        return path

    def _get(self, url: str, limit: int):
        with self._lock:
            if self.stats["requests"] >= self._max_requests:
                raise WebHdfsError("WebHDFS request budget exhausted")
            self.stats["requests"] += 1
        try:
            response = self._opener.open(
                Request(url, method="GET"), timeout=self._timeout
            )
        except HTTPError as exc:
            response = exc
        with response:
            status = int(response.status)
            headers = {key.lower(): value for key, value in response.headers.items()}
            body = b""
            if status == 200:
                try:
                    if int(headers.get("content-length", "0")) > limit:
                        raise WebHdfsError("WebHDFS response exceeds byte limit")
                except ValueError:
                    raise WebHdfsError("invalid WebHDFS response length") from None
                body = response.read(limit + 1)
                if len(body) > limit:
                    raise WebHdfsError("WebHDFS response exceeds byte limit")
                with self._lock:
                    self.stats["bytes_read"] += len(body)
            return status, headers, body

    def _redirect(self, location: str, path: str) -> str:
        try:
            parsed = urlsplit(location)
            origin = _http_origin(
                urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
            )
            query = parse_qs(parsed.query, keep_blank_values=True)
            if (
                origin not in self._routes
                or parsed.fragment
                or _path(parsed.path) != "/webhdfs/v1" + path
                or query.get("op") != ["OPEN"]
                or ("offset" in query and query["offset"] != ["0"])
                or "length" in query
            ):
                raise ValueError("redirect changed the requested object or operation")
            return self._routes[origin] + parsed.path + "?" + parsed.query
        except (ValueError, UnicodeError):
            raise WebHdfsError(
                "WebHDFS redirect is outside the configured read boundary"
            ) from None

    def _request(self, uri: str, operation: str, limit: int) -> bytes:
        if type(limit) is not int or not 0 <= limit <= self._max_bytes:
            raise ValueError("invalid response byte limit")
        path = self._uri_path(uri)
        query = urlencode({"op": operation, "user.name": self._user})
        url = self._base_url + quote(path, safe="/=") + "?" + query
        for attempt in range(self._attempts):
            retry = False
            try:
                status, headers, body = self._get(url, limit)
                if status == 307 and operation == "OPEN":
                    target = self._redirect(headers.get("location", ""), path)
                    status, _, body = self._get(target, limit)
                if status == 200:
                    return body
                retry = status in {429, 500, 502, 503, 504}
                if not retry:
                    raise WebHdfsError(f"WebHDFS read rejected (HTTP {status})")
            except (URLError, TimeoutError, ConnectionError):
                retry = True
            if retry and attempt + 1 < self._attempts:
                with self._lock:
                    self.stats["retries"] += 1
                self._sleep(min(0.25 * (2**attempt), 2))
            else:
                raise WebHdfsError("WebHDFS read exhausted bounded retries") from None
        raise AssertionError("unreachable")

    def read(self, uri: str, *, max_bytes: int) -> bytes:
        return self._request(uri, "OPEN", max_bytes)

    def stat(self, uri: str) -> dict:
        try:
            value = json.loads(
                self._request(uri, "GETFILESTATUS", min(self._max_bytes, 65536))
            )["FileStatus"]
            if not isinstance(value, dict) or value.get("type") not in {
                "FILE",
                "DIRECTORY",
            }:
                raise ValueError("invalid file status")
            if type(value.get("length")) is not int or value["length"] < 0:
                raise ValueError("invalid file length")
            return value
        except (KeyError, TypeError, ValueError):
            raise WebHdfsError("invalid WebHDFS file status") from None

    def list_directory(self, uri: str, *, max_entries: int = 4096) -> tuple[dict, ...]:
        """Child entries of one directory, as `{"pathSuffix", "type", "length"}`.

        Added for S15P21E102-220's job intake, which must discover run
        directories it was not told about in advance. The public GitHub source
        never needed this — its configuration names one published snapshot
        root — so listing was not part of this reader until now.

        Still GET-only and still inside the pinned namespace: `LISTSTATUS`
        goes through the same `_request`, so the byte bound, request budget,
        retry policy and redirect refusal all apply unchanged. A caller cannot
        reach outside `uri_prefix` any more than `read` can.

        Entries are returned in the order the NameNode gave them and are not
        interpreted here; deciding which child is a usable run belongs to the
        caller, not to the transport.
        """

        if type(max_entries) is not int or not 1 <= max_entries <= 100_000:
            raise ValueError("invalid directory entry bound")
        try:
            listing = json.loads(self._request(uri, "LISTSTATUS", self._max_bytes))
            entries = listing["FileStatuses"]["FileStatus"]
            if type(entries) is not list:
                raise ValueError("invalid directory listing")
            if len(entries) > max_entries:
                raise ValueError("directory listing exceeds the configured bound")
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("type") not in {
                    "FILE",
                    "DIRECTORY",
                }:
                    raise ValueError("invalid directory entry")
                suffix = entry.get("pathSuffix")
                if type(suffix) is not str or not suffix or "/" in suffix:
                    raise ValueError("invalid directory entry name")
            return tuple(entries)
        except (KeyError, TypeError, ValueError):
            raise WebHdfsError("invalid WebHDFS directory listing") from None
