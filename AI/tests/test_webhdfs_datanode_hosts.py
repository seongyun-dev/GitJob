"""Rewriting the WebHDFS 307 DataNode host for a caller off the cluster network.

A WebHDFS read or write is two hops. The NameNode answers `307` and names the
DataNode in `Location` using that DataNode's *own* container hostname, so a
caller outside the Compose network resolves the first hop and fails the second.
Before this, a scheduled run on the laptop collected and then quietly kept its
files locally — the confusion S15P21E102-189 and `docs/data/README.md` §14.1
record.

No network: every case drives a recording fake transport, following
`test_job_raw_sink.py`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest
from common.webhdfs import (
    WebHdfsClient,
    WebHdfsError,
    WebHdfsResponse,
    parse_datanode_hosts,
    rewrite_datanode_host,
)
from job.collector.raw_sink import sink_from_env

NAMENODE = "http://100.70.66.38:9870/webhdfs/v1"
# What the operational cluster actually returns, captured on 2026-09-10.
REDIRECT = (
    "http://hdfs-datanode3:9864/webhdfs/v1/gitjob/raw/x?op=CREATE"
    "&namenoderpcaddress=hdfs-namenode:8020&overwrite=false"
)
HOST_MAP = (
    "hdfs-datanode:9864=100.70.66.38:9864,"
    "hdfs-datanode2:9864=100.70.66.38:9866,"
    "hdfs-datanode3:9864=100.70.66.38:9867"
)


# --- parsing ---------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "   ", ",", " , "])
def test_absent_map_is_the_in_cluster_default(value: str | None):
    """Unset must stay a no-op: on the data node the hostname resolves."""

    assert parse_datanode_hosts(value) == {}


def test_map_parses_every_datanode_with_its_published_port():
    """The right-hand ports differ — three DataNodes, three host ports."""

    assert parse_datanode_hosts(HOST_MAP) == {
        "hdfs-datanode:9864": "100.70.66.38:9864",
        "hdfs-datanode2:9864": "100.70.66.38:9866",
        "hdfs-datanode3:9864": "100.70.66.38:9867",
    }


def test_surrounding_whitespace_is_ignored():
    parsed = parse_datanode_hosts(" hdfs-datanode:9864 = 10.0.0.1:9864 , ")
    assert parsed == {"hdfs-datanode:9864": "10.0.0.1:9864"}


@pytest.mark.parametrize("value", ["hdfs-datanode:9864", "=10.0.0.1:9864", "a="])
def test_malformed_entries_are_rejected_rather_than_dropped(value: str):
    """A silently ignored entry would send the run back to the wrong cluster."""

    with pytest.raises(ValueError):
        parse_datanode_hosts(value)


# --- rewriting -------------------------------------------------------------


def test_empty_map_leaves_the_redirect_untouched():
    assert rewrite_datanode_host(REDIRECT, {}) == REDIRECT


def test_host_and_port_are_replaced_and_the_query_survives():
    """`namenoderpcaddress` is resolved server-side and must not be rewritten."""

    rewritten = rewrite_datanode_host(REDIRECT, parse_datanode_hosts(HOST_MAP))

    assert rewritten.startswith("http://100.70.66.38:9867/webhdfs/v1/gitjob/raw/x")
    assert "namenoderpcaddress=hdfs-namenode:8020" in rewritten


def test_a_bare_hostname_key_also_matches():
    rewritten = rewrite_datanode_host(REDIRECT, {"hdfs-datanode3": "10.0.0.9:9864"})

    assert rewritten.startswith("http://10.0.0.9:9864/")


def test_an_unmapped_datanode_fails_loudly():
    """A DataNode added on the server must not become a DNS timeout."""

    with pytest.raises(WebHdfsError, match="hdfs-datanode3:9864"):
        rewrite_datanode_host(REDIRECT, {"hdfs-datanode:9864": "10.0.0.1:9864"})


# --- the client follows the rewritten target -------------------------------


@dataclass
class RedirectingTransport:
    """A NameNode that redirects to a name only the cluster can resolve."""

    calls: list[tuple[str, str]] = field(default_factory=list)
    body: bytes = b"payload"

    def request(
        self,
        method: str,
        url: str,
        *,
        body: object | None = None,
        timeout: float,
    ) -> WebHdfsResponse:
        self.calls.append((method, url))
        if url.startswith("http://hdfs-datanode"):
            raise AssertionError(f"followed an unresolvable redirect: {url}")
        # The DataNode hop is matched first: its URL carries `op=CREATE` too.
        if url.startswith("http://100.70.66.38:9867/"):
            return WebHdfsResponse(201, {}, b"")
        if "op=CREATE" in url:
            return WebHdfsResponse(307, {"Location": REDIRECT}, b"")
        if "op=GETFILESTATUS" in url:
            return WebHdfsResponse(404, {}, b'{"RemoteException":{}}')
        if "op=MKDIRS" in url or "op=RENAME" in url or "op=DELETE" in url:
            return WebHdfsResponse(200, {}, json.dumps({"boolean": True}).encode())
        raise AssertionError(f"unexpected request {method} {url}")


def _client(transport: RedirectingTransport) -> WebHdfsClient:
    return WebHdfsClient(
        base_url=NAMENODE,
        transport=transport,
        datanode_hosts=parse_datanode_hosts(HOST_MAP),
    )


def test_upload_sends_the_bytes_to_the_reachable_datanode():
    transport = RedirectingTransport()

    _client(transport).store_immutable("/gitjob/raw/x", b"payload")

    uploads = [
        url for method, url in transport.calls if method == "PUT" and "9867" in url
    ]
    assert uploads, transport.calls


def test_read_follows_the_rewritten_redirect():
    transport = RedirectingTransport()
    transport.request = _reading(transport)  # type: ignore[method-assign]

    assert _client(transport).read("/gitjob/raw/x") == b"payload"


def _reading(transport: RedirectingTransport):
    """OPEN redirects once, then the DataNode returns the bytes."""

    def request(method: str, url: str, *, body: object | None = None, timeout: float):
        transport.calls.append((method, url))
        if url.startswith("http://hdfs-datanode"):
            raise AssertionError(f"followed an unresolvable redirect: {url}")
        if url.startswith("http://100.70.66.38:9867/"):
            return WebHdfsResponse(200, {}, b"payload")
        return WebHdfsResponse(307, {"Location": REDIRECT}, b"")

    return request


# --- the environment carries it into the collector -------------------------


def test_sink_from_env_reads_the_datanode_map():
    """`.env.wsl` sets both; `Infra/compose/compose.yaml` passes them through."""

    sink = sink_from_env({"WEBHDFS_URL": NAMENODE, "WEBHDFS_DATANODE_HOSTS": HOST_MAP})

    assert sink is not None
    assert sink.client.datanode_hosts["hdfs-datanode3:9864"] == "100.70.66.38:9867"


def test_sink_from_env_without_the_map_stays_in_cluster():
    sink = sink_from_env({"WEBHDFS_URL": "http://hdfs-namenode:9870/webhdfs/v1"})

    assert sink is not None
    assert sink.client.datanode_hosts == {}


# --- urllib must not chase the redirect on its own -------------------------


def test_the_stdlib_transport_surfaces_a_307_instead_of_following_it():
    """The regression that made a read fail while a write succeeded.

    urllib follows a `307` on GET but not on PUT. While it did, `OPEN` never
    reached the rewrite and a run off the cluster network could publish but
    not read back. A loopback server is used rather than a fake, because the
    behaviour under test belongs to urllib, not to our code.
    """

    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from common.webhdfs import UrllibWebHdfsTransport

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(307)
            self.send_header("Location", REDIRECT)
            self.end_headers()

        def log_message(self, *args):  # keep pytest output clean
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = UrllibWebHdfsTransport().request(
            "GET",
            f"http://127.0.0.1:{server.server_port}/webhdfs/v1/x?op=OPEN",
            timeout=10,
        )
    finally:
        server.shutdown()
        server.server_close()

    assert response.status == 307
    assert response.headers["Location"] == REDIRECT
