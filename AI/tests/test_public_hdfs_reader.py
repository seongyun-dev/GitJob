"""Bounded, namespace-scoped GET reads with explicit DataNode routing."""

import io
from urllib.error import URLError

import pytest

from common.webhdfs import WebHdfsError
from github.artifact_reader import ReadOnlyWebHdfsReader

PREFIX = "hdfs:///gitjob/input/snapshot-1"
BASE = "http://namenode:9870/webhdfs/v1"
URI = PREFIX + "/artifacts/package.json"


class Response(io.BytesIO):
    def __init__(self, body=b"", *, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}


class Opener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append((request.full_url, request.method, timeout))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def reader(opener, **kwargs):
    return ReadOnlyWebHdfsReader(
        BASE,
        PREFIX,
        datanode_routes={"http://datanode:9864": "http://100.70.66.38:9864"},
        opener=opener,
        sleep=lambda _: None,
        **kwargs,
    )


def redirect(
    path="/gitjob/input/snapshot-1/artifacts/package.json",
    origin="http://datanode:9864",
    query="op=OPEN",
):
    return Response(
        status=307, headers={"Location": origin + "/webhdfs/v1" + path + "?" + query}
    )


def test_reads_exact_namespace_through_explicit_datanode_route():
    opener = Opener(redirect(), Response(b"abc"))
    value = reader(opener)
    assert value.read(URI, max_bytes=3) == b"abc"
    assert len(opener.requests) == 2
    assert all(method == "GET" for _, method, _ in opener.requests)
    assert opener.requests[1][0].startswith(
        "http://100.70.66.38:9864/webhdfs/v1/gitjob/input/"
    )
    assert value.stats["requests"] == 2
    assert value.stats["bytes_read"] == 3


@pytest.mark.parametrize(
    "uri",
    [
        "http://example.invalid/a",
        PREFIX + "-other/a",
        PREFIX + "/../secret",
        PREFIX + "/%2e%2e/secret",
        PREFIX + "/%252e%252e/secret",
        URI + "?op=DELETE",
        URI + "#fragment",
        "hdfs://other/gitjob/input/snapshot-1/a",
    ],
)
def test_rejects_uri_escape_before_network(uri):
    opener = Opener()
    with pytest.raises(ValueError):
        reader(opener).read(uri, max_bytes=50)
    assert not opener.requests


@pytest.mark.parametrize(
    "location",
    [
        redirect(origin="http://unknown:9864"),
        redirect(path="/outside/a"),
        redirect(query="op=DELETE"),
        redirect(query="op=OPEN&op=DELETE"),
        redirect(origin="http://user:secret@datanode:9864"),
        redirect(query="op=OPEN&offset=1"),
    ],
)
def test_rejects_redirect_authority_path_or_operation_changes(location):
    opener = Opener(location)
    with pytest.raises(WebHdfsError):
        reader(opener).read(URI, max_bytes=3)
    assert len(opener.requests) == 1


def test_never_follows_a_second_redirect_or_reads_above_cap():
    opener = Opener(redirect(), redirect())
    with pytest.raises(WebHdfsError):
        reader(opener).read(URI, max_bytes=3)
    opener = Opener(Response(b"abcd"))
    with pytest.raises(WebHdfsError):
        reader(opener).read(URI, max_bytes=3)


def test_retries_only_transient_get_failure_and_has_total_budget():
    opener = Opener(URLError("offline"), Response(b"ok"))
    value = reader(opener, max_requests=2)
    assert value.read(URI, max_bytes=2) == b"ok"
    assert value.stats["retries"] == 1
    with pytest.raises(WebHdfsError):
        value.read(URI, max_bytes=2)
    assert len(opener.requests) == 2
    opener = Opener(Response(status=403))
    with pytest.raises(WebHdfsError):
        reader(opener).read(URI, max_bytes=2)
    assert len(opener.requests) == 1


def test_status_is_bounded_and_read_only():
    opener = Opener(Response(b'{"FileStatus":{"type":"FILE","length":3}}'))
    assert reader(opener).stat(URI)["length"] == 3
    assert "op=GETFILESTATUS" in opener.requests[0][0]
    assert opener.requests[0][1] == "GET"


def test_configs_do_not_allow_credentials_or_unbounded_reads():
    with pytest.raises(ValueError):
        ReadOnlyWebHdfsReader("http://user:secret@host/webhdfs/v1", PREFIX)
    with pytest.raises(ValueError):
        reader(Opener()).read(URI, max_bytes=100_000_000_000)
