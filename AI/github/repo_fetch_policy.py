"""Pure artifact-selection policy for GitHub repository trees."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any

from github.contracts import (
    RepoCollectionIssue,
    RepoCollectionPolicy,
    RepoLanguageMetadata,
)

MANIFEST_BASENAMES = (
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "go.mod",
    "Cargo.toml",
    "composer.json",
    "Gemfile",
    "Dockerfile",
    "Jenkinsfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
)
DEVOPS_KUBERNETES_BASENAMES = frozenset(
    {
        "deployment.yml",
        "deployment.yaml",
        "service.yml",
        "service.yaml",
        "statefulset.yml",
        "statefulset.yaml",
        "daemonset.yml",
        "daemonset.yaml",
        "configmap.yml",
        "configmap.yaml",
        "namespace.yml",
        "namespace.yaml",
        "ingress.yml",
        "ingress.yaml",
        "job.yml",
        "job.yaml",
        "cronjob.yml",
        "cronjob.yaml",
    }
)
DEVOPS_KUBERNETES_DIRS = frozenset(
    {"k8s", "kubernetes", "manifests", "deploy", "deployment"}
)
LANGUAGE_SUFFIXES = {
    "C": frozenset({".c"}),
    "C++": frozenset({".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx"}),
    "C#": frozenset({".cs"}),
    "Go": frozenset({".go"}),
    "Python": frozenset({".py"}),
    "Java": frozenset({".java"}),
    "Kotlin": frozenset({".kt", ".kts"}),
    "JavaScript": frozenset({".cjs", ".js", ".jsx", ".mjs"}),
    "TypeScript": frozenset({".cts", ".mts", ".ts", ".tsx"}),
    "HTML": frozenset({".html", ".htm"}),
    "CSS": frozenset({".css", ".less", ".sass", ".scss"}),
    "SQL": frozenset({".sql"}),
}
MANIFEST_DEPRIORITY_SEGMENTS = {
    "example",
    "examples",
    "fixture",
    "fixtures",
    "generated",
    "sample",
    "samples",
    "test",
    "tests",
}
SOURCE_SUFFIXES = (
    ".py",
    ".java",
    ".kt",
    ".kts",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".rb",
    ".php",
)
EXCLUDED_SEGMENTS = {
    ".git",
    ".gradle",
    ".idea",
    ".mvn",
    ".next",
    ".venv",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "vendor",
}
EXCLUDED_SOURCE_SUFFIXES = (
    ".bundle.js",
    ".generated.java",
    ".min.js",
)


@dataclass(frozen=True)
class RepoFetchPolicy:
    """Operational limits and deterministic selection rules for one run."""

    policy_version: str
    top_n_limit: int
    max_api_calls: int
    max_runtime_seconds: int
    max_tree_entries: int = 100_000
    max_artifact_files: int = 24
    max_artifact_bytes: int = 1_048_576
    max_manifest_files: int = 24
    max_source_files: int = 0
    max_file_bytes: int = 262_144
    max_depth: int = 8
    source_prefix_bytes: int = 8_192
    rate_limit_safety_threshold: int = 200
    manifest_selection_version: str = "manifest-priority/v4"

    def __post_init__(self) -> None:
        positive = {
            "top_n_limit": self.top_n_limit,
            "max_api_calls": self.max_api_calls,
            "max_runtime_seconds": self.max_runtime_seconds,
            "max_tree_entries": self.max_tree_entries,
            "max_artifact_files": self.max_artifact_files,
            "max_artifact_bytes": self.max_artifact_bytes,
            "max_manifest_files": self.max_manifest_files,
            "max_file_bytes": self.max_file_bytes,
            "max_depth": self.max_depth,
            "source_prefix_bytes": self.source_prefix_bytes,
        }
        if not self.policy_version.strip():
            raise ValueError("policy_version must not be blank")
        if not self.manifest_selection_version.strip():
            raise ValueError("manifest_selection_version must not be blank")
        for name, value in positive.items():
            if value < 1:
                raise ValueError(f"{name} must be positive")
        if self.max_source_files < 0:
            raise ValueError("max_source_files cannot be negative")
        if self.rate_limit_safety_threshold < 0:
            raise ValueError("rate_limit_safety_threshold cannot be negative")
        if self.max_manifest_files > self.max_artifact_files:
            raise ValueError("max_manifest_files exceeds max_artifact_files")
        if self.max_source_files > self.max_artifact_files:
            raise ValueError("max_source_files exceeds max_artifact_files")

    def contract_policy(self) -> RepoCollectionPolicy:
        return RepoCollectionPolicy(
            policy_version=self.policy_version,
            top_n_limit=self.top_n_limit,
            max_api_calls=self.max_api_calls,
            max_runtime_seconds=self.max_runtime_seconds,
            max_tree_entries=self.max_tree_entries,
            max_artifact_files=self.max_artifact_files,
            max_artifact_bytes=self.max_artifact_bytes,
        )

    @property
    def cache_identity(self) -> str:
        """Bind reuse to every effective policy value, not its label alone."""

        encoded = json.dumps(
            asdict(self),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return f"{self.policy_version}:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True)
class ArtifactSelection:
    manifest_paths: tuple[str, ...]
    source_paths: tuple[str, ...]
    issues: tuple[RepoCollectionIssue, ...]
    manifest_candidate_count: int = 0
    manifest_selected_count: int = 0
    manifest_excluded_count: int = 0
    manifest_excluded_reasons: tuple[str, ...] = ()

    def metrics(self) -> dict[str, Any]:
        return {
            "manifest_candidate_count": self.manifest_candidate_count,
            "manifest_selected_count": self.manifest_selected_count,
            "manifest_excluded_count": self.manifest_excluded_count,
            "manifest_excluded_reasons": list(self.manifest_excluded_reasons),
        }


def summarize_language_metadata(
    tree_entries: Sequence[Mapping[str, Any]],
    *,
    representative_limit: int = 3,
) -> tuple[RepoLanguageMetadata, ...]:
    """Summarize source-like paths without reading source contents."""

    if representative_limit < 1:
        raise ValueError("representative_limit must be positive")
    paths_by_language: dict[str, list[str]] = {name: [] for name in LANGUAGE_SUFFIXES}
    for entry in tree_entries:
        if entry.get("type") != "blob":
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not _safe_path(path):
            continue
        if _excluded(path, max_depth=64):
            continue
        suffix = PurePosixPath(path).suffix.casefold()
        for language, suffixes in LANGUAGE_SUFFIXES.items():
            if suffix in suffixes:
                paths_by_language[language].append(path)
                break
    return tuple(
        RepoLanguageMetadata(
            language=language,
            file_count=len(paths),
            representative_paths=tuple(sorted(paths)[:representative_limit]),
        )
        for language, paths in paths_by_language.items()
        if paths
    )


def devops_artifact_category(path: str) -> str | None:
    """Classify supported operational artifacts by path, without file reads."""

    candidate = PurePosixPath(path)
    basename = candidate.name.casefold()
    if basename == "dockerfile" or basename.startswith("dockerfile-"):
        return "DOCKERFILE"
    if basename == "jenkinsfile":
        return "JENKINSFILE"
    if basename.startswith(("docker-compose", "compose.")) and basename.endswith(
        (".yml", ".yaml")
    ):
        return "COMPOSE"
    parts = tuple(part.casefold() for part in candidate.parts)
    if (
        len(parts) >= 3
        and parts[0] == ".github"
        and parts[1] == "workflows"
        and basename.endswith((".yml", ".yaml"))
    ):
        return "GITHUB_ACTIONS"
    if basename in DEVOPS_KUBERNETES_BASENAMES and any(
        part in DEVOPS_KUBERNETES_DIRS for part in parts[:-1]
    ):
        return "KUBERNETES"
    return None


def select_artifacts(
    tree_entries: Sequence[Mapping[str, Any]],
    policy: RepoFetchPolicy,
) -> ArtifactSelection:
    """Select named manifests, then source prefixes only when no manifest exists."""

    eligible: list[tuple[str, int | None]] = []
    issues: list[RepoCollectionIssue] = []
    for entry in tree_entries[: policy.max_tree_entries]:
        path = entry.get("path")
        if entry.get("type") != "blob" or not isinstance(path, str):
            continue
        if not _safe_path(path) or _excluded(path, policy.max_depth):
            continue
        size = entry.get("size")
        typed_size = size if isinstance(size, int) and size >= 0 else None
        eligible.append((path, typed_size))

    if len(tree_entries) > policy.max_tree_entries:
        issues.append(RepoCollectionIssue.TREE_LIMIT_REACHED)

    priority = {name.casefold(): index for index, name in enumerate(MANIFEST_BASENAMES)}
    manifest_candidates = [
        (path, size)
        for path, size in eligible
        if _manifest_priority(path, priority) is not None
    ]
    manifest_candidates.sort(key=lambda item: _manifest_priority(item[0], priority))
    candidate_count = len(manifest_candidates)
    size_candidates = _within_file_size(manifest_candidates, policy, issues)
    oversized_count = candidate_count - len(size_candidates)
    if len(size_candidates) > policy.max_manifest_files:
        issues.append(RepoCollectionIssue.FILE_LIMIT_REACHED)
    selected_manifests = tuple(
        path for path, _ in size_candidates[: policy.max_manifest_files]
    )

    selected_sources: tuple[str, ...] = ()
    if not selected_manifests and policy.max_source_files:
        source_candidates = [
            (path, size)
            for path, size in eligible
            if path.lower().endswith(SOURCE_SUFFIXES)
            and not path.lower().endswith(EXCLUDED_SOURCE_SUFFIXES)
        ]
        source_candidates.sort(key=lambda item: (item[0].count("/"), item[0]))
        sources = _within_file_size(source_candidates, policy, issues)
        if len(sources) > policy.max_source_files:
            issues.append(RepoCollectionIssue.FILE_LIMIT_REACHED)
        selected_sources = tuple(path for path, _ in sources[: policy.max_source_files])

    combined_count = len(selected_manifests) + len(selected_sources)
    if combined_count > policy.max_artifact_files:
        issues.append(RepoCollectionIssue.FILE_LIMIT_REACHED)
        remaining = policy.max_artifact_files - len(selected_manifests)
        selected_sources = selected_sources[: max(remaining, 0)]

    excluded_reasons: list[str] = []
    if oversized_count:
        excluded_reasons.append("BYTE_LIMIT_REACHED")
    if candidate_count - oversized_count > len(selected_manifests):
        excluded_reasons.append("FILE_LIMIT_REACHED")

    return ArtifactSelection(
        manifest_paths=selected_manifests,
        source_paths=selected_sources,
        issues=tuple(dict.fromkeys(issues)),
        manifest_candidate_count=candidate_count,
        manifest_selected_count=len(selected_manifests),
        manifest_excluded_count=candidate_count - len(selected_manifests),
        manifest_excluded_reasons=tuple(excluded_reasons),
    )


def _within_file_size(
    candidates: Sequence[tuple[str, int | None]],
    policy: RepoFetchPolicy,
    issues: list[RepoCollectionIssue],
) -> list[tuple[str, int | None]]:
    allowed = []
    for candidate in candidates:
        if candidate[1] is not None and candidate[1] > policy.max_file_bytes:
            if RepoCollectionIssue.BYTE_LIMIT_REACHED not in issues:
                issues.append(RepoCollectionIssue.BYTE_LIMIT_REACHED)
            continue
        allowed.append(candidate)
    return allowed


def _safe_path(path: str) -> bool:
    if not path or path != path.strip() or "\\" in path:
        return False
    candidate = PurePosixPath(path)
    return not candidate.is_absolute() and all(
        part not in {"", ".", ".."} for part in candidate.parts
    )


def _excluded(path: str, max_depth: int) -> bool:
    candidate = PurePosixPath(path)
    if len(candidate.parts) - 1 > max_depth:
        return True
    return any(part.casefold() in EXCLUDED_SEGMENTS for part in candidate.parts)


def _manifest_priority(
    path: str, priority: Mapping[str, int]
) -> tuple[int, int, int, int, str] | None:
    """Return a stable root/module/generic priority for supported manifests."""

    candidate = PurePosixPath(path)
    basename = candidate.name.casefold()
    parent = candidate.parts[-2].casefold() if len(candidate.parts) >= 2 else None
    name_priority = priority.get(basename)
    if name_priority is None:
        if basename == "libs.versions.toml" and len(candidate.parts) >= 2:
            if parent != "gradle":
                return None
            name_priority = len(priority)
        elif basename.endswith(".txt") and parent == "requirements":
            name_priority = len(priority) + 1
        elif basename.endswith(".csproj"):
            name_priority = len(priority) + 2
        elif devops_artifact_category(path) is not None:
            name_priority = len(priority) + 3
        else:
            return None

    lowered_parts = {part.casefold() for part in candidate.parts[:-1]}
    deprioritized = bool(lowered_parts & MANIFEST_DEPRIORITY_SEGMENTS)
    location_priority = 0 if len(candidate.parts) == 1 else 1
    if basename == "libs.versions.toml" or parent == "requirements":
        location_priority = 1
    return (
        2 if deprioritized else 0,
        location_priority,
        name_priority,
        len(candidate.parts),
        path,
    )
