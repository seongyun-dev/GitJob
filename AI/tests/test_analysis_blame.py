"""Line attribution, against real git repositories.

Mocking git here would test the mock. The one failure that matters -- blame
succeeding on a shallow checkout and crediting everything to one commit -- is
invisible unless a real repository with real history is involved.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from analysis.blame import (
    BlameError,
    ShallowRepositoryError,
    blame_files,
    is_shallow,
)

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed"
)


def git(repository: Path, *args: str, **env: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        check=True,
        env={
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "GIT_AUTHOR_NAME": "A",
            "GIT_AUTHOR_EMAIL": "a@example.com",
            "GIT_COMMITTER_NAME": "A",
            "GIT_COMMITTER_EMAIL": "a@example.com",
            **env,
        },
    )
    return result.stdout


def commit(repository: Path, path: str, body: str, *, who: str) -> str:
    (repository / path).parent.mkdir(parents=True, exist_ok=True)
    (repository / path).write_text(body, encoding="utf-8")
    git(repository, "add", path)
    git(
        repository,
        "commit",
        "-m",
        f"{who} edits {path}",
        GIT_AUTHOR_NAME=who,
        GIT_AUTHOR_EMAIL=f"{who}@example.com",
        GIT_COMMITTER_NAME=who,
        GIT_COMMITTER_EMAIL=f"{who}@example.com",
    )
    return git(repository, "rev-parse", "HEAD").strip()


@pytest.fixture
def two_author_repository(tmp_path: Path) -> tuple[Path, str, str]:
    """A file whose lines come from two different commits."""
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "--quiet", "--initial-branch", "main")

    first = commit(origin, "App.java", "import a.B;\nimport a.C;\n", who="ann")
    second = commit(
        origin, "App.java", "import a.B;\nimport a.C;\nimport a.D;\n", who="bob"
    )
    return origin, first, second


def test_each_line_is_credited_to_the_commit_that_wrote_it(two_author_repository):
    origin, first, second = two_author_repository

    authors = blame_files(origin, {"App.java": {1, 3}})

    by_line = {a.line_no: a.commit_sha for a in authors}
    assert by_line == {1: first, 3: second}


def test_only_the_requested_lines_come_back(two_author_repository):
    # 저장소 하나에 파일 수천 개다. 근거가 가리키는 줄만 묻는 것이 이 함수의 전제다.
    origin, _, _ = two_author_repository

    authors = blame_files(origin, {"App.java": {2}})

    assert [a.line_no for a in authors] == [2]


def test_consecutive_lines_are_asked_as_one_range(two_author_repository):
    # import 세 줄이 붙어 나오는 일이 흔하다. 결과가 달라지지 않아야 한다.
    origin, first, second = two_author_repository

    authors = blame_files(origin, {"App.java": {1, 2, 3}})

    assert {a.line_no for a in authors} == {1, 2, 3}
    assert {a.commit_sha for a in authors} == {first, second}


def test_a_shallow_checkout_is_refused(tmp_path, two_author_repository):
    """이 테스트가 이 모듈이 존재하는 이유다.

    얕은 클론에서 blame 은 실패하지 않는다. 커밋이 하나뿐이라 모든 줄을 그 커밋에
    돌리고, 출력은 멀쩡해 보인다. 그대로 쓰면 모든 기여가 마지막에 푸시한 사람의
    것이 된다.
    """
    origin, _, second = two_author_repository
    shallow = tmp_path / "shallow"
    git(tmp_path, "clone", "--quiet", "--depth", "1", f"file://{origin}", str(shallow))

    assert is_shallow(shallow) is True
    with pytest.raises(ShallowRepositoryError):
        blame_files(shallow, {"App.java": {1, 3}})

    # 거부하지 않았다면 무엇이 나왔을지 -- 두 줄이 같은 커밋으로 뭉개진다.
    naive = subprocess.run(
        ["git", "blame", "--porcelain", "-L", "1,3", "--", "App.java"],
        cwd=shallow,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    shas = {line[:40] for line in naive.splitlines() if len(line) > 40 and line[:40].isalnum()}
    assert shas == {second}, "얕은 클론은 오류 없이 한 커밋으로 뭉갠다"


def test_a_full_clone_is_not_shallow(tmp_path, two_author_repository):
    origin, first, second = two_author_repository
    full = tmp_path / "full"
    git(tmp_path, "clone", "--quiet", f"file://{origin}", str(full))

    assert is_shallow(full) is False
    by_line = {a.line_no: a.commit_sha for a in blame_files(full, {"App.java": {1, 3}})}
    assert by_line == {1: first, 3: second}


def test_a_missing_file_is_skipped_not_fatal(two_author_repository):
    # 지워졌거나 이름이 바뀐 파일 하나 때문에 나머지 근거를 버리지 않는다.
    origin, first, _ = two_author_repository

    authors = blame_files(origin, {"App.java": {1}, "Gone.java": {1}})

    assert [(a.file_path, a.commit_sha) for a in authors] == [("App.java", first)]


def test_empty_line_sets_are_ignored(two_author_repository):
    origin, _, _ = two_author_repository

    assert blame_files(origin, {"App.java": set()}) == []


def test_a_line_that_looks_like_a_header_is_not_parsed_as_one(tmp_path):
    """소스 한 줄이 porcelain 헤더처럼 생길 수 있다.

    내용 줄은 탭으로 시작하므로 그것으로 구분한다. 내용을 헤더로 읽으면 엉뚱한
    커밋이 근거의 작성자가 된다.
    """
    origin = tmp_path / "tricky"
    origin.mkdir()
    git(origin, "init", "--quiet", "--initial-branch", "main")
    sha = commit(
        origin,
        "App.java",
        "// " + "d" * 40 + " 1 2 3\nimport a.B;\n",
        who="ann",
    )

    authors = blame_files(origin, {"App.java": {1, 2}})

    assert {a.commit_sha for a in authors} == {sha}


def test_git_failure_surfaces_as_blame_error(tmp_path):
    not_a_repository = tmp_path / "plain"
    not_a_repository.mkdir()

    with pytest.raises(BlameError):
        is_shallow(not_a_repository)


def test_reformatting_a_line_does_not_steal_its_authorship(tmp_path):
    """-w 가 없으면 포맷터를 돌린 사람이 기여를 가져간다.

    이 모듈의 다른 오차는 전부 "본인 기여를 놓치는" 쪽인데 이것만 반대다 --
    만들지 않은 기술이 개인 판정에 잡힌다. 그래서 따로 고정한다.
    """
    origin = tmp_path / "formatted"
    origin.mkdir()
    git(origin, "init", "--quiet", "--initial-branch", "main")

    wrote_it = commit(
        origin, "App.java",
        "package a;\nimport org.springframework.boot.SpringApplication;\n",
        who="teammate",
    )
    # 그 줄의 들여쓰기만 바꾼다. 내용이 바뀌므로 blame 이 따라 움직인다.
    commit(
        origin, "App.java",
        "package a;\n    import org.springframework.boot.SpringApplication;\n",
        who="formatter",
    )

    authors = blame_files(origin, {"App.java": {2}})

    assert [a.commit_sha for a in authors] == [wrote_it], (
        "공백만 바꾼 커밋이 기여를 가져갔다 -- -w 가 빠졌는지 확인할 것"
    )


def test_moving_a_line_without_changing_it_keeps_authorship(tmp_path):
    # git 이 이미 따라가는 경우다. -w 없이도 맞는다는 것을 함께 남겨,
    # 위 테스트가 무엇을 더 막는지 드러나게 한다.
    origin = tmp_path / "moved"
    origin.mkdir()
    git(origin, "init", "--quiet", "--initial-branch", "main")

    wrote_it = commit(origin, "App.java", "package a;\nimport b.C;\n", who="teammate")
    commit(origin, "App.java", "package a;\n\nimport b.C;\n", who="formatter")

    authors = blame_files(origin, {"App.java": {3}})

    assert [a.commit_sha for a in authors] == [wrote_it]
