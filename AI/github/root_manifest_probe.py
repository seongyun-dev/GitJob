"""Measure whether the recursive tree is needed to find a dependency manifest.

The recursive tree is 98.6% of all bytes the fetch benchmark downloads, and it
costs one REST core call.  This probe asks the cheaper question directly: fetch
the known manifest basenames at the repository root over ``raw.githubusercontent.com``,
which is not part of the documented REST core budget, and compare what it finds
against the manifest set the recursive tree reported for the same commit.

It is a measurement tool for S15P21E102-104, not a production fetch path.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RAW_ROOT = "https://raw.githubusercontent.com"
DEFAULT_HEAD_BYTES = 2048
DEFAULT_WORKERS = 8

# Ordered by observed frequency so an early stop pays off on the positive cases.
PROBE_BASENAMES: tuple[str, ...] = (
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "composer.json",
    "Gemfile",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
)

# Probed only to test whether the 12-name list, rather than the repositories,
# explains a low manifest yield.
WIDENED_BASENAMES: tuple[str, ...] = (
    "setup.py",
    "setup.cfg",
    "Pipfile",
    "environment.yml",
    "CMakeLists.txt",
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    "pubspec.yaml",
    "mix.exs",
    "Podfile",
    "Package.swift",
    "go.sum",
    "package-lock.json",
    "yarn.lock",
    "Gemfile.lock",
    "tsconfig.json",
    "build.sbt",
)

# Distinguishes "this file is absent" from "this commit is not reachable".
LIVENESS_BASENAMES: tuple[str, ...] = (
    "README.md",
    ".gitignore",
    "LICENSE",
    "index.html",
)


@dataclass(frozen=True)
class ProbeTarget:
    repo_id: int
    repo_name: str
    commit_sha: str
    rank: int
    tree_manifest_paths: tuple[str, ...]


@dataclass(frozen=True)
class ProbeResult:
    target: ProbeTarget
    found: dict[str, tuple[str, ...]]
    requests: int
    bytes_read: int
    elapsed_seconds: float

    @property
    def reachable(self) -> bool:
        return bool(self.found.get("liveness")) or bool(self.found.get("probe"))

    def as_dict(self) -> dict[str, Any]:
        tree_root = tuple(
            path for path in self.target.tree_manifest_paths if "/" not in path
        )
        return {
            "repo_id": self.target.repo_id,
            "repo_name": self.target.repo_name,
            "rank": self.target.rank,
            "commit_sha": self.target.commit_sha,
            "tree_manifest_count": len(self.target.tree_manifest_paths),
            "tree_root_manifests": list(tree_root),
            "probe_found": list(self.found.get("probe", ())),
            "widened_found": list(self.found.get("widened", ())),
            "liveness_found": list(self.found.get("liveness", ())),
            "reachable": self.reachable,
            "raw_requests": self.requests,
            "bytes_read": self.bytes_read,
            "elapsed_seconds": self.elapsed_seconds,
        }


def _fetch_head(url: str, head_bytes: int, timeout: float) -> tuple[int, int]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "GitJob-Root-Manifest-Probe/1.0",
            "Range": f"bytes=0-{max(0, head_bytes - 1)}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), len(response.read())
    except urllib.error.HTTPError as error:
        return int(error.code), 0
    except (OSError, TimeoutError):
        return 0, 0


def probe_repository(
    target: ProbeTarget,
    *,
    widen: bool = False,
    head_bytes: int = DEFAULT_HEAD_BYTES,
    timeout: float = 25.0,
    fetch: Callable[[str, int, float], tuple[int, int]] = _fetch_head,
    pause_seconds: float = 0.0,
) -> ProbeResult:
    """Probe one commit's root for manifests.  Consumes no REST core budget."""
    groups: list[tuple[str, Sequence[str]]] = [("probe", PROBE_BASENAMES)]
    if widen:
        groups.append(("widened", WIDENED_BASENAMES))
    groups.append(("liveness", LIVENESS_BASENAMES))

    encoded_repo = "/".join(
        urllib.parse.quote(part, safe="") for part in target.repo_name.split("/")
    )
    found: dict[str, tuple[str, ...]] = {}
    requests = 0
    bytes_read = 0
    started = time.perf_counter()
    for group, basenames in groups:
        hits: list[str] = []
        for basename in basenames:
            url = f"{RAW_ROOT}/{encoded_repo}/{target.commit_sha}/{urllib.parse.quote(basename, safe='')}"
            status, size = fetch(url, head_bytes, timeout)
            requests += 1
            bytes_read += size
            if status in {200, 206}:
                hits.append(basename)
            if pause_seconds:
                time.sleep(pause_seconds)
        found[group] = tuple(hits)
    return ProbeResult(
        target=target,
        found=found,
        requests=requests,
        bytes_read=bytes_read,
        elapsed_seconds=time.perf_counter() - started,
    )


def targets_from_checkpoint(payload: Mapping[str, Any]) -> list[ProbeTarget]:
    """Every SUCCEEDED repository with a pinned commit, from a benchmark checkpoint."""
    repos = payload.get("repos")
    if not isinstance(repos, Mapping):
        raise TypeError("checkpoint payload has no repos mapping")
    targets: list[ProbeTarget] = []
    for entry in repos.values():
        if not isinstance(entry, Mapping):
            continue
        result = entry.get("result")
        if not isinstance(result, Mapping) or result.get("status") != "SUCCEEDED":
            continue
        commit_sha = result.get("pinned_commit_sha")
        if not commit_sha:
            continue
        targets.append(
            ProbeTarget(
                repo_id=int(result["repo_id"]),
                repo_name=str(result.get("canonical_repo_name") or result["repo_name"]),
                commit_sha=str(commit_sha),
                rank=int(result.get("rank", 0)),
                tree_manifest_paths=tuple(result.get("manifest_candidates", ())),
            )
        )
    targets.sort(key=lambda item: item.rank)
    return targets


def summarize(results: Sequence[ProbeResult]) -> dict[str, Any]:
    """Compare root probing against the recursive tree on the same commits."""
    reachable = [item for item in results if item.reachable]
    tree_positive = [item for item in reachable if item.target.tree_manifest_paths]
    probe_positive = [item for item in reachable if item.found.get("probe")]
    widened_only = [
        item
        for item in reachable
        if item.found.get("widened")
        and not item.found.get("probe")
        and not item.target.tree_manifest_paths
    ]
    agree = [
        item
        for item in reachable
        if bool(item.found.get("probe")) == bool(item.target.tree_manifest_paths)
    ]
    return {
        "schema_version": "github-root-manifest-probe/v1",
        "probed": len(results),
        "reachable": len(reachable),
        "core_calls": 0,
        "raw_requests": sum(item.requests for item in results),
        "bytes_read": sum(item.bytes_read for item in results),
        "elapsed_seconds": sum(item.elapsed_seconds for item in results),
        "tree_positive": len(tree_positive),
        "root_probe_positive": len(probe_positive),
        "widened_list_only": len(widened_only),
        "agreement": len(agree),
        "agreement_rate": (len(agree) / len(reachable)) if reachable else None,
        "recall_vs_tree": (
            len([item for item in tree_positive if item.found.get("probe")])
            / len(tree_positive)
        )
        if tree_positive
        else None,
    }


def run(arguments: argparse.Namespace) -> dict[str, Any]:
    payload = json.loads(arguments.checkpoint.read_text(encoding="utf-8"))
    targets = targets_from_checkpoint(payload)
    if arguments.limit is not None:
        targets = targets[: arguments.limit]

    def work(target: ProbeTarget) -> ProbeResult:
        return probe_repository(
            target, widen=arguments.widen, pause_seconds=arguments.pause_seconds
        )

    with ThreadPoolExecutor(max_workers=arguments.workers) as pool:
        results = list(pool.map(work, targets))
    summary = summarize(results)
    summary["rows"] = [item.as_dict() for item in results]
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Probe repository roots for dependency manifests over raw.githubusercontent.com "
            "and compare the result with the recursive tree."
        )
    )
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--pause-seconds", type=float, default=0.02)
    parser.add_argument(
        "--widen",
        action="store_true",
        help="also probe 18 further basenames, to test whether the 12-name list is the limit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    summary = run(arguments)
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    with arguments.out.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(
        json.dumps(
            {key: value for key, value in summary.items() if key != "rows"}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
