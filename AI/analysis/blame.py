"""Who last wrote each line that produced a piece of evidence.

The worker answers "which commit", never "whose commit". Deciding whether a
commit belongs to the requesting user needs that user's identity, and the
request topic must not carry it -- the topic outlives the person's consent and
their addresses. The backend resolves the commit to a GitHub account afterwards,
where the token already lives.

## Shallow checkouts are the trap

`git blame` on a `--depth 1` checkout does not fail. There is exactly one commit
in the repository, so every line is attributed to it and the output looks
perfectly ordinary. Measured on spring-petclinic: 40 files blamed, zero errors,
every line credited to `818c4136...` -- the tip. Used as-is, every contributor's
work would be credited to whoever pushed last.

An error would have been safer than that answer, so `blame_files` refuses to run
on a shallow repository instead of producing one.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "BlameError",
    "LineAuthor",
    "ShallowRepositoryError",
    "blame_files",
    "is_shallow",
]


class BlameError(RuntimeError):
    """Blame could not be produced for a reason the caller should see."""


class ShallowRepositoryError(BlameError):
    """The checkout has no history, so authorship cannot be read from it."""


@dataclass(frozen=True)
class LineAuthor:
    """One line of one file, and the commit that last changed it."""

    file_path: str
    line_no: int
    commit_sha: str


def is_shallow(repository: Path) -> bool:
    """True when the checkout was fetched with a depth limit.

    Asked before every blame. `git rev-parse` is used rather than looking for
    `.git/shallow`, because a worktree keeps its git directory elsewhere.
    """
    result = _git(["rev-parse", "--is-shallow-repository"], repository)
    return result.strip() == "true"


def blame_files(
    repository: Path,
    targets: dict[str, set[int]],
    *,
    timeout_seconds: int = 300,
) -> list[LineAuthor]:
    """Attribute the given lines of the given files.

    `targets` maps a repository-relative path to the line numbers that produced
    evidence. Only those lines are blamed -- a repository has thousands of files
    and tens of thousands of lines, and all but a few hundred are irrelevant.

    A file that cannot be blamed is skipped rather than failing the analysis. It
    was deleted, renamed beyond git's detection, or is binary; none of those is a
    reason to throw away the rest of the evidence. The lines simply stay
    unattributed, which the backend reads as "not verified".
    """
    if is_shallow(repository):
        raise ShallowRepositoryError(
            "cannot attribute lines in a shallow checkout: every line would be "
            "credited to the single fetched commit"
        )

    authors: list[LineAuthor] = []
    for file_path, lines in targets.items():
        if not lines:
            continue
        try:
            authors.extend(
                _blame_one(repository, file_path, lines, timeout_seconds=timeout_seconds)
            )
        except BlameError:
            continue
    return authors


def _blame_one(
    repository: Path,
    file_path: str,
    lines: set[int],
    *,
    timeout_seconds: int,
) -> list[LineAuthor]:
    """Blame one file over the ranges that cover the wanted lines.

    Consecutive lines are collapsed into one `-L` range. Evidence tends to come
    in runs (three imports on lines 10-12), so this turns three arguments into
    one without changing the result.
    """
    # `-w` ignores whitespace-only changes. Without it, reformatting a line --
    # re-indenting, re-wrapping, sorting imports -- moves its attribution to
    # whoever ran the formatter. That is the one error path here that
    # *over*-credits: a technology the person never introduced would count
    # toward their personal level. Everything else this module gets wrong
    # errs toward missing a contribution, which is the safer direction.
    #
    # Measured on a two-author repository: a teammate writes the import, we
    # change only its indentation. Plain blame answers "me"; with `-w` it
    # answers "teammate". Moving the line without touching it is already
    # handled -- git follows that on its own.
    #
    # `-M` follows code moved within the file, for the same reason.
    #
    # `--no-color` is not passed: git blame rejects it as ambiguous with
    # --no-color-lines / --no-color-by-age, and porcelain is never colored.
    args = ["blame", "--porcelain", "-w", "-M"]
    for start, end in _ranges(lines):
        args += ["-L", f"{start},{end}"]
    args += ["--", file_path]

    output = _git(args, repository, timeout_seconds=timeout_seconds)
    return _parse_porcelain(output, file_path, lines)


def _ranges(lines: set[int]) -> list[tuple[int, int]]:
    """Collapse a set of line numbers into ascending inclusive ranges."""
    ordered = sorted(lines)
    ranges: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for line in ordered[1:]:
        if line == previous + 1:
            previous = line
            continue
        ranges.append((start, previous))
        start = previous = line
    ranges.append((start, previous))
    return ranges


def _parse_porcelain(output: str, file_path: str, wanted: set[int]) -> list[LineAuthor]:
    """Read the commit of each line from porcelain output.

    The format opens every group with `<sha> <orig-line> <final-line> [count]`
    and follows it with header lines and one tab-prefixed content line per line
    of the group. Only the group headers are needed, and the content lines are
    skipped without being parsed -- a source line can otherwise look like a
    header (`deadbeef 1 2` is valid code).
    """
    authors: list[LineAuthor] = []
    expected = 0
    sha = ""
    final_line = 0

    for raw in output.splitlines():
        if raw.startswith("\t"):
            # The line's own content. It closes one line of the current group.
            if expected > 0:
                if final_line in wanted:
                    authors.append(
                        LineAuthor(file_path=file_path, line_no=final_line, commit_sha=sha)
                    )
                final_line += 1
                expected -= 1
            continue
        if expected > 0:
            # A header inside the current group (author, summary, filename...).
            continue
        parts = raw.split(" ")
        if len(parts) >= 3 and len(parts[0]) == 40:
            sha = parts[0]
            try:
                final_line = int(parts[2])
                expected = int(parts[3]) if len(parts) >= 4 else 1
            except ValueError:
                expected = 0
    return authors


def _git(args: list[str], repository: Path, *, timeout_seconds: int = 60) -> str:
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", *args],
            cwd=repository,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as missing:
        raise BlameError("git is not available") from missing
    except subprocess.TimeoutExpired as slow:
        raise BlameError(f"git {args[0]} timed out") from slow
    if completed.returncode != 0:
        raise BlameError(f"git {args[0]} failed: {completed.stderr.strip()[:200]}")
    return completed.stdout
