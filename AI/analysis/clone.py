"""Fetch exactly one commit of one repository onto local disk.

### Why not `git clone --branch`

The contract says the worker analyzes `commit_sha` even after the branch moves,
and between the request and this fetch the branch usually has moved. Cloning a
branch and hoping the SHA is still reachable is a race. Fetching the SHA
directly is not: GitHub serves it or it does not exist.

    git init
    git remote add origin <url>
    git fetch --depth 1 origin <sha>
    git checkout FETCH_HEAD

`--depth 1` downloads that one commit's tree. Contribution analysis will need
history later; that is a larger `--depth`, not a different mechanism.

### Failures are split before they are reported

A network blip should be retried; a deleted repository should not. Retrying a
deleted repository forever is how a consumer group stops making progress, so
anything not recognised as transient is treated as terminal and sent to the DLQ,
where it is visible instead of silently looping.
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "CloneResult",
    "CredentialRequiredCloneError",
    "PermanentCloneError",
    "RepositoryCloner",
    "TransientCloneError",
    "UnsafeWorkPathError",
]


class CloneError(RuntimeError):
    """Base for fetch failures, carrying the code that reaches the operator."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TransientCloneError(CloneError):
    """Worth retrying: the offset is not committed and the claim is released."""


class PermanentCloneError(CloneError):
    """Not worth retrying: recorded, sent to the DLQ, offset committed."""


class CredentialRequiredCloneError(CloneError):
    """Anonymous GitHub response that must be retried with authorised access."""


class UnsafeWorkPathError(ValueError):
    """A checkout target is not an isolated directory below the work root."""


# Matched against git's stderr. Everything unmatched is permanent on purpose.
_TRANSIENT = (
    re.compile(r"could not resolve host", re.IGNORECASE),
    re.compile(r"connection (timed out|reset|refused)", re.IGNORECASE),
    re.compile(r"failed to connect", re.IGNORECASE),
    re.compile(r"the remote end hung up", re.IGNORECASE),
    re.compile(r"unable to access .*: (50\d|429)", re.IGNORECASE),
    re.compile(r"rate limit", re.IGNORECASE),
    re.compile(r"early eof", re.IGNORECASE),
)
_NOT_FOUND = re.compile(
    r"(repository not found|not found|does not exist|does not appear to be a git repository)",
    re.IGNORECASE,
)
# git asks for a username when a repository is private or missing. With
# GIT_TERMINAL_PROMPT=0 it fails instead of hanging, and this is that failure.
_NEEDS_AUTH = re.compile(
    r"(could not read username|authentication failed|terminal prompts disabled)", re.IGNORECASE
)


@dataclass(frozen=True)
class CloneResult:
    path: Path
    bytes_on_disk: int


@dataclass
class RepositoryCloner:
    """One fetch per call. The caller owns cleanup of `work_root`."""

    work_root: Path
    github_base_url: str = "https://github.com"
    timeout_seconds: int = 600
    max_bytes: int = 2 * 1024 * 1024 * 1024
    #: Fetch the whole history instead of one commit.
    #:
    #: Contribution analysis needs it: `git blame` on a shallow checkout does not
    #: fail, it attributes every line to the single commit that was fetched. The
    #: answer looks fine and is wrong, which is worse than an error.
    #:
    #: Measured on spring-petclinic, blaming 40 files:
    #:
    #:     depth 1                 clone 1.4s   disk  3MB   blame  2.1s  (wrong)
    #:     full                    clone 4.0s   disk 13MB   blame  2.7s
    #:     --filter=blob:none      clone 2.5s   disk  4MB   blame 10m37s
    #:     --filter=tree:0         clone 3.0s   disk  3MB   blame 35m18s
    #:
    #: Partial clones save a second on the fetch and pay it back 240-800x in
    #: blame, because every missing blob is a round trip. Full history is the
    #: only option that both works and finishes.
    with_history: bool = False

    def fetch(
        self,
        full_name: str,
        commit_sha: str,
        into: str,
        *,
        access_token: str | None = None,
    ) -> CloneResult:
        target = self._target(into)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True)

        url = f"{self.github_base_url.rstrip('/')}/{full_name}.git"
        self._git(["init", "--quiet"], target, "init")
        self._git(["remote", "add", "origin", url], target, "remote")
        depth = [] if self.with_history else ["--depth", "1"]
        self._git(
            ["-c", "protocol.version=2", "fetch", *depth, "--quiet", "origin", commit_sha],
            target,
            "fetch",
            access_token=access_token,
        )
        self._git(["checkout", "--quiet", "FETCH_HEAD"], target, "checkout")

        size = _directory_bytes(target)
        if size > self.max_bytes:
            # Checked after the fact because git cannot be asked in advance.
            # Left to the caller to clean up, as with any other failure.
            raise PermanentCloneError(
                "REPOSITORY_TOO_LARGE",
                f"{full_name} is {size} bytes on disk, over the {self.max_bytes} limit",
            )
        return CloneResult(path=target, bytes_on_disk=size)

    def cleanup(self, into: str) -> None:
        """Remove one checkout only after repeating the containment check."""

        target = self._target(into)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)

    def _target(self, into: str) -> Path:
        """Resolve a non-symlinked child without trusting its identifier."""

        requested = Path(into)
        if requested.is_absolute():
            raise UnsafeWorkPathError("work target must be relative")

        root = self.work_root.resolve()
        candidate = root.joinpath(requested)
        current = root
        for part in requested.parts:
            current = current / part
            if current.is_symlink() or current.is_junction():
                raise UnsafeWorkPathError(
                    "work target must not traverse a symbolic link or junction"
                )

        resolved = candidate.resolve()
        if resolved == root or not resolved.is_relative_to(root):
            raise UnsafeWorkPathError("work target must be a child of the work root")
        return resolved

    def _git(
        self,
        args: list[str],
        cwd: Path,
        operation: str,
        *,
        access_token: str | None = None,
    ) -> None:
        """`operation` is reported separately: args[0] may be a `-c` override."""
        environment = {
            **os.environ,
            # Never block waiting for credentials that this process does not
            # have. Private repositories fail fast instead of hanging until the
            # broker takes the partition away.
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            # A developer machine may have a GitHub credential helper in the
            # global config. Public-first must remain truly anonymous and use
            # only the credential obtained for this analysis request.
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GCM_INTERACTIVE": "never",
        }
        redactions: tuple[str, ...] = ()
        if access_token is not None:
            # Git reads this config only in the child process. The token never
            # enters argv, the remote URL, or a repository config file.
            basic = base64.b64encode(
                f"x-access-token:{access_token}".encode()
            ).decode("ascii")
            environment.update(
                {
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "http.extraHeader",
                    "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
                }
            )
            redactions = (access_token, basic)
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=environment,
                check=False,
            )
        except FileNotFoundError as error:
            raise PermanentCloneError(
                "GIT_NOT_AVAILABLE", "git is not installed"
            ) from error
        except subprocess.TimeoutExpired as error:
            raise TransientCloneError(
                "CLONE_TIMEOUT", f"git {operation} exceeded {self.timeout_seconds}s"
            ) from error
        if completed.returncode != 0:
            raise _classify(
                operation,
                _redact(completed.stderr, redactions),
                credential_supplied=access_token is not None,
            )


def _classify(
    operation: str, stderr: str, *, credential_supplied: bool = False
) -> CloneError:
    text = stderr.strip()
    if _NEEDS_AUTH.search(text):
        if not credential_supplied:
            return CredentialRequiredCloneError(
                "REPOSITORY_CREDENTIAL_REQUIRED",
                f"git {operation} requires authorised repository access",
            )
        return PermanentCloneError(
            "GITHUB_RECONNECT_REQUIRED",
            f"git {operation} rejected the authorised repository access",
        )
    if _NOT_FOUND.search(text):
        # GitHub intentionally uses the same anonymous 404 for private and
        # missing repositories. Only an authorised retry can distinguish them.
        if not credential_supplied:
            return CredentialRequiredCloneError(
                "REPOSITORY_CREDENTIAL_REQUIRED",
                f"git {operation} requires authorised repository access",
            )
        return PermanentCloneError(
            "REPOSITORY_NOT_ACCESSIBLE",
            f"git {operation} could not access the repository or commit",
        )
    for pattern in _TRANSIENT:
        if pattern.search(text):
            return TransientCloneError(
                "GITHUB_UNAVAILABLE", f"git {operation} failed: {text[:200]}"
            )
    return PermanentCloneError("CLONE_FAILED", f"git {operation} failed: {text[:200]}")


def _redact(text: str, values: tuple[str, ...]) -> str:
    redacted = text
    for value in values:
        if value:
            redacted = redacted.replace(value, "[REDACTED]")
    return redacted


def _directory_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            total += path.stat().st_size
    return total
