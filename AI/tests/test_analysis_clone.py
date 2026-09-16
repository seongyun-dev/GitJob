"""Clone behaviour against real local git repositories.

`git` is used for real here rather than mocked. The value of these tests is in
what git actually does with a SHA fetch and how its stderr reads on failure, and
a mock would only assert what we already believe. No network: the "remote" is a
repository on disk.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from analysis.clone import (
    CredentialRequiredCloneError,
    PermanentCloneError,
    RepositoryCloner,
    UnsafeWorkPathError,
)

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed"
)


def _run(*args: str, cwd) -> str:
    done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def origin(tmp_path, commits: int = 2):
    """A local repository standing in for GitHub, plus its commit SHAs."""
    # Named with the .git suffix so the URL the cloner builds
    # ("<base>/<full_name>.git") resolves here, exactly as it does for GitHub.
    root = tmp_path / "origin.git"
    root.mkdir()
    _run("git", "init", "--quiet", "--initial-branch=main", ".", cwd=root)
    _run("git", "config", "user.email", "t@example.com", cwd=root)
    _run("git", "config", "user.name", "Test", cwd=root)
    # A SHA fetch reads the remote's advertised refs; without this, git refuses
    # to serve a commit that is not the tip of a ref.
    _run("git", "config", "uploadpack.allowAnySHA1InWant", "true", cwd=root)
    shas = []
    for index in range(commits):
        (root / f"file{index}.txt").write_text(f"content {index}\n")
        _run("git", "add", ".", cwd=root)
        _run("git", "commit", "--quiet", "-m", f"commit {index}", cwd=root)
        shas.append(_run("git", "rev-parse", "HEAD", cwd=root))
    return root, shas


def cloner(tmp_path, root) -> RepositoryCloner:
    work = tmp_path / "work"
    work.mkdir()
    # full_name is appended to the base URL, so a local path base makes
    # "<tmp>/origin.git" resolve to the repository above.
    return RepositoryCloner(work_root=work, github_base_url=str(root.parent))


@contextmanager
def authenticated_git_server(tmp_path, source, token: str):
    """Serve a real dumb-HTTP Git remote that requires the expected Basic header."""

    served = tmp_path / "served"
    served.mkdir()
    bare = served / "private.git"
    _run("git", "clone", "--quiet", "--bare", str(source), str(bare), cwd=served)
    _run("git", "update-server-info", cwd=bare)
    expected = "basic " + base64.b64encode(f"x-access-token:{token}".encode()).decode()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(served), **kwargs)

        def do_GET(self):
            if self.headers.get("Authorization") != expected:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="private-git"')
                self.end_headers()
                return
            super().do_GET()

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_checks_out_the_requested_commit_not_the_branch_tip(tmp_path):
    root, shas = origin(tmp_path, commits=3)
    older = shas[0]

    result = cloner(tmp_path, root).fetch("origin", older, "an_1")

    head = _run("git", "rev-parse", "HEAD", cwd=result.path)
    assert head == older
    # The later commits' files must not be present: this is the whole point of
    # pinning, since the branch has moved on since the request.
    assert (result.path / "file0.txt").exists()
    assert not (result.path / "file2.txt").exists()


def test_reports_the_size_it_put_on_disk(tmp_path):
    root, shas = origin(tmp_path)
    result = cloner(tmp_path, root).fetch("origin", shas[-1], "an_1")

    assert result.bytes_on_disk > 0


def test_an_oversized_repository_is_a_permanent_failure(tmp_path):
    root, shas = origin(tmp_path)
    small = cloner(tmp_path, root)
    small.max_bytes = 1

    with pytest.raises(PermanentCloneError) as failure:
        small.fetch("origin", shas[-1], "an_1")

    assert failure.value.code == "REPOSITORY_TOO_LARGE"


def test_an_unknown_commit_is_permanent_not_retried(tmp_path):
    root, _ = origin(tmp_path)
    missing = "0" * 40

    with pytest.raises(PermanentCloneError):
        cloner(tmp_path, root).fetch("origin", missing, "an_1")


def test_a_missing_repository_is_permanent_not_retried(tmp_path):
    root, shas = origin(tmp_path)

    # GitHub deliberately returns the same anonymous response for a missing
    # repository and a private repository. The caller must try its authorised
    # credential before deciding that the repository is gone.
    with pytest.raises(CredentialRequiredCloneError):
        cloner(tmp_path, root).fetch("does-not-exist", shas[-1], "an_1")


def test_access_token_is_only_passed_in_the_child_environment(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs["env"]))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr("analysis.clone.subprocess.run", run)
    secret = "github-secret-that-must-not-reach-argv"

    RepositoryCloner(work_root=work).fetch(
        "octocat/private", "a" * 40, "an_1", access_token=secret
    )

    assert all(secret not in repr(argv) for argv, _ in calls)
    fetch_call = next(call for call in calls if "fetch" in call[0])
    assert all(env["GIT_CONFIG_GLOBAL"] == os.devnull for _, env in calls)
    assert fetch_call[1]["GIT_CONFIG_COUNT"] == "1"
    assert fetch_call[1]["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert secret not in fetch_call[1]["GIT_CONFIG_VALUE_0"]
    assert all("GIT_CONFIG_VALUE_0" not in env for argv, env in calls if "fetch" not in argv)


def test_access_token_and_derived_header_are_redacted_from_git_errors(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    secret = "github-secret"
    basic = base64.b64encode(f"x-access-token:{secret}".encode()).decode("ascii")

    def run(argv, **_kwargs):
        if "fetch" in argv:
            return subprocess.CompletedProcess(
                argv, 1, "", f"fatal: rejected {secret} header {basic}"
            )
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr("analysis.clone.subprocess.run", run)

    with pytest.raises(PermanentCloneError) as failure:
        RepositoryCloner(work_root=work).fetch(
            "octocat/private", "a" * 40, "an_1", access_token=secret
        )

    assert secret not in str(failure.value)
    assert basic not in str(failure.value)


def test_authenticated_http_full_history_clone_is_pinned_without_persisting_token(tmp_path):
    source, shas = origin(tmp_path, commits=3)
    pinned = shas[-1]
    secret = "github-private-token"
    work = tmp_path / "private-work"
    work.mkdir()

    with authenticated_git_server(tmp_path, source, secret) as base_url:
        fetcher = RepositoryCloner(
            work_root=work,
            github_base_url=base_url,
            # Python's static test server provides Git's dumb HTTP protocol,
            # which deliberately has no shallow capability. The unit test
            # above covers the same header injection for the shallow argv.
            with_history=True,
        )
        with pytest.raises(CredentialRequiredCloneError):
            fetcher.fetch("private", pinned, "an_1")

        result = fetcher.fetch("private", pinned, "an_1", access_token=secret)

    assert _run("git", "rev-parse", "HEAD", cwd=result.path) == pinned
    assert _run("git", "rev-list", "--count", "HEAD", cwd=result.path) == "3"
    config = (result.path / ".git" / "config").read_text(encoding="utf-8")
    encoded = base64.b64encode(f"x-access-token:{secret}".encode()).decode()
    assert secret not in config
    assert encoded not in config


def test_a_rerun_replaces_a_leftover_directory(tmp_path):
    root, shas = origin(tmp_path)
    fetcher = cloner(tmp_path, root)
    stale = fetcher.work_root / "an_1"
    stale.mkdir()
    (stale / "stale.txt").write_text("from a previous attempt\n")

    result = fetcher.fetch("origin", shas[-1], "an_1")

    assert not (result.path / "stale.txt").exists()


@pytest.mark.parametrize("operation", ["fetch", "cleanup"])
@pytest.mark.parametrize("into", ["../outside", "."])
def test_work_target_cannot_escape_or_equal_the_work_root(tmp_path, operation, into):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("must remain", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    fetcher = RepositoryCloner(work_root=work)

    with pytest.raises(UnsafeWorkPathError):
        if operation == "fetch":
            fetcher.fetch("owner/repo", "a" * 40, into)
        else:
            fetcher.cleanup(into)

    assert sentinel.read_text(encoding="utf-8") == "must remain"


def test_absolute_work_target_is_rejected_without_deleting_it(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("must remain", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    fetcher = RepositoryCloner(work_root=work)

    with pytest.raises(UnsafeWorkPathError):
        fetcher.cleanup(str(outside.resolve()))

    assert sentinel.read_text(encoding="utf-8") == "must remain"


def test_symlinked_work_target_is_rejected_without_following_it(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("must remain", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    link = work / "an_1"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks are unavailable: {error}")
    fetcher = RepositoryCloner(work_root=work)

    with pytest.raises(UnsafeWorkPathError):
        fetcher.cleanup("an_1")

    assert sentinel.read_text(encoding="utf-8") == "must remain"


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are Windows-specific")
def test_junction_cannot_redirect_cleanup_to_another_work_directory(
    tmp_path, monkeypatch
):
    work = tmp_path / "work"
    work.mkdir()
    other_attempt = work / "other-attempt"
    other_attempt.mkdir()
    sentinel = other_attempt / "keep.txt"
    sentinel.write_text("must remain", encoding="utf-8")
    junction = work / "an_1"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(other_attempt)],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip(f"directory junctions are unavailable: {created.stderr}")

    attempted_cleanup = []
    monkeypatch.setattr(
        "analysis.clone.shutil.rmtree", lambda path, **_: attempted_cleanup.append(path)
    )
    try:
        with pytest.raises(UnsafeWorkPathError):
            RepositoryCloner(work_root=work).cleanup("an_1")
    finally:
        junction.rmdir()

    assert attempted_cleanup == []
    assert sentinel.read_text(encoding="utf-8") == "must remain"
