"""Attribute Rule Pack evidence lines at one pinned commit.

Git identifies the commit that last wrote an evidence line.  A B-owned resolver
then maps only those distinct commit SHAs to GitHub logins and supplies the
target GitHub login.  Tokens, email addresses, and user/database identifiers do
not enter this module or the repository-analysis Kafka event.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from analysis.judge import EvidenceFact

_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
Attribution = Literal["SELF", "OTHER", "UNKNOWN"]


@dataclass(frozen=True)
class IdentityResolution:
    """B-supplied GitHub identity result for one repository analysis."""

    target_login: str | None
    author_logins: dict[str, str | None]


class CommitAuthorIdentityResolver(Protocol):
    """Boundary owned by B; implementations may batch GitHub GraphQL calls."""

    def resolve(
        self, analysis_repository_id: str, commit_shas: tuple[str, ...]
    ) -> IdentityResolution: ...


@dataclass
class FixtureIdentityResolver:
    """Deterministic local/canary resolver; never guesses from git email."""

    target_login: str | None
    author_logins: dict[str, str | None]
    requested_commit_shas: tuple[str, ...] = field(default=(), init=False)

    def resolve(
        self, _analysis_repository_id: str, commit_shas: tuple[str, ...]
    ) -> IdentityResolution:
        self.requested_commit_shas = commit_shas
        return IdentityResolution(self.target_login, dict(self.author_logins))


@dataclass(frozen=True)
class AttributedEvidence:
    evidence: EvidenceFact
    fact_id: str
    repository_analysis_id: str
    attribution: Attribution
    attribution_commit_sha: str | None
    missing_scope: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Blame:
    commit_sha: str | None
    missing_scope: str | None = None


@dataclass
class GitEvidenceAttributor:
    """Resolve evidence lines with bounded history growth from the pinned SHA."""

    max_deepen_commits: int = 256
    deepen_step: int = 64
    timeout_seconds: int = 120

    def __post_init__(self) -> None:
        if self.max_deepen_commits < 0:
            raise ValueError("max_deepen_commits must not be negative")
        if self.deepen_step < 1:
            raise ValueError("deepen_step must be positive")

    def attribute(
        self,
        checkout: Path,
        pinned_commit_sha: str,
        analysis_repository_id: str,
        evidence: tuple[EvidenceFact, ...],
        resolver: CommitAuthorIdentityResolver,
    ) -> tuple[AttributedEvidence, ...]:
        if not _COMMIT_SHA.fullmatch(pinned_commit_sha):
            raise ValueError("pinned_commit_sha must be 40 lowercase hex characters")

        remaining_deepen = [self.max_deepen_commits]
        blame_cache: dict[tuple[str, int], _Blame] = {}
        blamed = []
        for item in evidence:
            key = (item.fact.file, item.fact.line)
            if item.fact.fact_type == "SOURCE_FILE":
                blame = _Blame(None, "EVIDENCE_LINE_UNAVAILABLE")
            elif key in blame_cache:
                blame = blame_cache[key]
            else:
                blame = self._blame_line(
                    checkout,
                    pinned_commit_sha,
                    key[0],
                    key[1],
                    remaining_deepen,
                )
                blame_cache[key] = blame
            blamed.append(blame)
        commit_shas = tuple(
            sorted({item.commit_sha for item in blamed if item.commit_sha is not None})
        )
        resolution = resolver.resolve(analysis_repository_id, commit_shas)
        target = _normalize_login(resolution.target_login)

        attributed: list[AttributedEvidence] = []
        for item, blame in zip(evidence, blamed, strict=True):
            if blame.missing_scope:
                attributed.append(
                    AttributedEvidence(
                        item,
                        item.fact_id,
                        analysis_repository_id,
                        "UNKNOWN",
                        None,
                        (blame.missing_scope,),
                    )
                )
                continue
            assert blame.commit_sha is not None
            author = _normalize_login(resolution.author_logins.get(blame.commit_sha))
            if target is None:
                attribution, missing = "UNKNOWN", ("TARGET_IDENTITY_UNRESOLVED",)
            elif author is None:
                attribution, missing = "UNKNOWN", ("AUTHOR_IDENTITY_UNRESOLVED",)
            else:
                attribution = "SELF" if author == target else "OTHER"
                missing = ()
            attributed.append(
                AttributedEvidence(
                    item,
                    item.fact_id,
                    analysis_repository_id,
                    attribution,
                    blame.commit_sha,
                    missing,
                )
            )
        return tuple(attributed)

    def _blame_line(
        self,
        checkout: Path,
        pinned: str,
        relative_path: str,
        line: int,
        remaining_deepen: list[int],
    ) -> _Blame:
        if line < 1 or not _safe_relative_path(relative_path):
            return _Blame(None, "EVIDENCE_LINE_UNAVAILABLE")

        blame = self._run_blame(checkout, pinned, relative_path, line)
        if blame is None:
            return _Blame(None, "EVIDENCE_LINE_UNAVAILABLE")
        commit_sha, boundary = blame
        if not boundary or not self._is_shallow(checkout):
            return _Blame(commit_sha)

        while remaining_deepen[0] > 0 and self._is_shallow(checkout):
            amount = min(self.deepen_step, remaining_deepen[0])
            remaining_deepen[0] -= amount
            if not self._deepen(checkout, pinned, amount):
                break
            blame = self._run_blame(checkout, pinned, relative_path, line)
            if blame is None:
                return _Blame(None, "EVIDENCE_LINE_UNAVAILABLE")
            commit_sha, boundary = blame
            if not boundary or not self._is_shallow(checkout):
                return _Blame(commit_sha)
        return _Blame(None, "BLAME_HISTORY_INCOMPLETE")

    def _run_blame(
        self, checkout: Path, pinned: str, relative_path: str, line: int
    ) -> tuple[str, bool] | None:
        completed = self._git(
            checkout,
            "blame",
            "--line-porcelain",
            "-L",
            f"{line},{line}",
            pinned,
            "--",
            relative_path,
        )
        if completed.returncode != 0:
            return None
        lines = completed.stdout.splitlines()
        if not lines:
            return None
        commit_sha = lines[0].split(" ", 1)[0]
        if not _COMMIT_SHA.fullmatch(commit_sha):
            return None
        return commit_sha, "boundary" in lines[1:]

    def _is_shallow(self, checkout: Path) -> bool:
        completed = self._git(checkout, "rev-parse", "--is-shallow-repository")
        return completed.returncode != 0 or completed.stdout.strip() == "true"

    def _deepen(self, checkout: Path, pinned: str, amount: int) -> bool:
        return (
            self._git(
                checkout,
                "-c",
                "protocol.version=2",
                "fetch",
                "--quiet",
                "--deepen",
                str(amount),
                "origin",
                pinned,
            ).returncode
            == 0
        )

    def _git(self, checkout: Path, *args: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=checkout,
                capture_output=True,
                check=False,
                text=True,
                timeout=self.timeout_seconds,
                env={
                    **os.environ,
                    "GIT_TERMINAL_PROMPT": "0",
                    "GCM_INTERACTIVE": "never",
                },
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return subprocess.CompletedProcess(["git", *args], 1, "", "git unavailable")


def _normalize_login(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip().casefold()


def _safe_relative_path(value: str) -> bool:
    return (
        bool(value)
        and not value.startswith("/")
        and ":" not in value
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )
