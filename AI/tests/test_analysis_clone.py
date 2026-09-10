"""Clone behaviour against real local git repositories.

`git` is used for real here rather than mocked. The value of these tests is in
what git actually does with a SHA fetch and how its stderr reads on failure, and
a mock would only assert what we already believe. No network: the "remote" is a
repository on disk.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from analysis.clone import PermanentCloneError, RepositoryCloner, UnsafeWorkPathError

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

    with pytest.raises(PermanentCloneError):
        cloner(tmp_path, root).fetch("does-not-exist", shas[-1], "an_1")


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
