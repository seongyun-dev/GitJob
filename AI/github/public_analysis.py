"""Consume pinned public snapshots as positive Registry observations, never absence."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol
from urllib.parse import unquote, urlsplit

import tomllib
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)

from github.contracts import (
    GitHubRepoSnapshotBatch,
    RepoArtifact,
    RepoArtifactType,
    RepoCollectionStatus,
)
from registry.contracts import ImportEcosystem, PackageEcosystem
from registry.mapper import MapperInput, MapperSource, MatchStatus, RegistryMapper
from trend.contracts import TrendStatus

PUBLIC_PARSER_VERSION = "c-public-static-observations/v4"
PUBLIC_SCHEMA_VERSION = "c-public-repo-analysis/v1"
MAX_CONSUMER_ARTIFACT_BYTES = 2_000_000
MAX_CONSUMER_BATCH_BYTES = 100_000_000


class ArtifactReader(Protocol):
    def read(self, uri: str, *, max_bytes: int) -> bytes: ...


class LocalMirrorArtifactReader:
    """Read an operator-configured URI namespace mirrored below one local directory."""

    def __init__(self, root: Path, uri_prefix: str) -> None:
        self.root = root.resolve(strict=True)
        self.uri_prefix = uri_prefix.rstrip("/") + "/"
        parsed = urlsplit(self.uri_prefix)
        if (
            not self.root.is_dir()
            or not parsed.scheme
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("a directory and a fixed absolute URI prefix are required")

    def read(self, uri: str, *, max_bytes: int) -> bytes:
        if max_bytes < 0 or max_bytes > MAX_CONSUMER_ARTIFACT_BYTES:
            raise ValueError("invalid artifact byte limit")
        if not uri.startswith(self.uri_prefix):
            raise ValueError("artifact URI is outside the configured namespace")
        relative = unquote(uri[len(self.uri_prefix) :])
        if any(character in relative for character in "\\:?\x00#") or any(
            part in {"", ".", ".."} for part in relative.split("/")
        ):
            raise ValueError("unsafe artifact mirror path")
        target = (self.root / Path(*relative.split("/"))).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("artifact mirror path escapes root")
        with target.open("rb") as stream:
            content = stream.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise ValueError("artifact exceeds byte limit")
        return content


class OutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TechnologyObservation(OutputModel):
    tech_id: str
    basis: str
    raw_value: str
    scope: str
    path: str
    uri: str
    content_hash: str
    line: int | None = None


class UnresolvedObservation(OutputModel):
    raw_value: str
    basis: str
    status: str
    candidates: tuple[str, ...]
    path: str
    scope: str


class ArtifactAnalysis(OutputModel):
    path: str
    uri: str
    content_hash: str
    size_bytes: int
    status: TrendStatus
    reason: str | None = None


class PublicRepoResult(OutputModel):
    repo_snapshot_id: str
    github_repo_id: int
    repo_full_name: str
    pinned_commit_sha: str
    tree_sha: str | None
    activity_metric: str
    activity_period_start: str
    activity_period_end: str
    activity_rank: int
    activity_count: int
    collection_status: RepoCollectionStatus
    collection_issues: tuple[str, ...]
    tree_truncated: bool
    observed_tree_entries: int
    checkpoint_uri: str | None
    reused_from_snapshot_id: str | None
    eligible: StrictBool
    included_in_denominator: StrictBool
    partial_included: StrictBool
    exclusion_reasons: tuple[str, ...]
    quality_reasons: tuple[str, ...]
    status: TrendStatus
    observations: tuple[TechnologyObservation, ...]
    unresolved: tuple[UnresolvedObservation, ...]
    artifacts: tuple[ArtifactAnalysis, ...]

    @model_validator(mode="after")
    def validate_eligibility(self) -> PublicRepoResult:
        parsed = any(
            artifact.status in {TrendStatus.READY, TrendStatus.INSUFFICIENT_DATA}
            and artifact.reason != "COLLECTION_POLICY_EXCLUDED"
            for artifact in self.artifacts
        )
        if self.included_in_denominator != (self.eligible and parsed):
            raise ValueError("denominator inclusion requires eligible parsed artifacts")
        if self.collection_status is RepoCollectionStatus.FAILED and self.eligible:
            raise ValueError("FAILED collections cannot be eligible")
        if not self.eligible and (self.observations or self.unresolved):
            raise ValueError("excluded collections cannot contribute observations")
        if self.partial_included != (
            self.eligible and self.collection_status is RepoCollectionStatus.PARTIAL
        ):
            raise ValueError("partial flag must reflect opted-in PARTIAL collection")
        if self.tree_sha == self.pinned_commit_sha and (
            "TREE_SHA_EQUALS_COMMIT_SHA" not in self.quality_reasons
            or self.status is TrendStatus.READY
        ):
            raise ValueError(
                "suspicious tree identity requires a non-ready quality flag"
            )
        return self


class PublicTechnologyCount(OutputModel):
    tech_id: str
    observed_repo_count: StrictInt = Field(ge=1)
    sample_repo_count: StrictInt = Field(ge=1)
    observation_ratio: float = Field(ge=0, le=1)
    github_repo_ids: tuple[int, ...]

    @model_validator(mode="after")
    def validate_numeric_bounds(self) -> PublicTechnologyCount:
        if not self.observed_repo_count == len(
            set(self.github_repo_ids)
        ) <= self.sample_repo_count or len(self.github_repo_ids) != len(
            set(self.github_repo_ids)
        ):
            raise ValueError(
                "observed repository IDs/count must be distinct and within denominator"
            )
        if self.observation_ratio != self.observed_repo_count / self.sample_repo_count:
            raise ValueError(
                "observation ratio must use accepted parsed repository denominator"
            )
        return self


class PublicBatchResult(OutputModel):
    schema_version: Literal["c-public-repo-analysis/v1"] = PUBLIC_SCHEMA_VERSION
    dataset_snapshot_id: str
    pipeline_run_id: str
    collector_version: str
    collection_policy_version: str
    generated_at: str
    registry_version: str
    parser_version: str = PUBLIC_PARSER_VERSION
    status: TrendStatus
    include_partial: StrictBool
    denominator_basis: Literal["ELIGIBLE_REPOSITORIES_WITH_PARSED_ARTIFACT"] = (
        "ELIGIBLE_REPOSITORIES_WITH_PARSED_ARTIFACT"
    )
    total_repo_count: StrictInt = Field(ge=0)
    eligible_repo_count: StrictInt = Field(ge=0)
    sample_repo_count: StrictInt = Field(ge=0)
    analyzed_repo_count: StrictInt = Field(ge=0)
    excluded_repo_count: StrictInt = Field(ge=0)
    records: tuple[PublicRepoResult, ...]
    technologies: tuple[PublicTechnologyCount, ...]

    @model_validator(mode="after")
    def reconcile_population(self) -> PublicBatchResult:
        if self.total_repo_count != len(
            self.records
        ) or self.eligible_repo_count != sum(
            record.eligible for record in self.records
        ):
            raise ValueError("public population must reconcile with input records")
        if (
            not self.sample_repo_count
            == self.analyzed_repo_count
            == sum(record.included_in_denominator for record in self.records)
        ):
            raise ValueError(
                "public denominator must equal parsed eligible repositories"
            )
        if self.excluded_repo_count != self.total_repo_count - self.analyzed_repo_count:
            raise ValueError("excluded count must reconcile with analyzed repositories")
        if not self.include_partial and any(
            record.partial_included for record in self.records
        ):
            raise ValueError("PARTIAL inclusion requires explicit opt-in")
        observed = defaultdict(set)
        for record in self.records:
            if record.included_in_denominator:
                for observation in record.observations:
                    observed[observation.tech_id].add(record.github_repo_id)
        if len({row.tech_id for row in self.technologies}) != len(
            self.technologies
        ) or set(observed) != {row.tech_id for row in self.technologies}:
            raise ValueError(
                "public aggregate technology IDs must reflect observations"
            )
        for row in self.technologies:
            if (
                row.sample_repo_count != self.sample_repo_count
                or set(row.github_repo_ids) != observed[row.tech_id]
            ):
                raise ValueError(
                    "public aggregate must use accepted observed repositories"
                )
        return self


@dataclass(frozen=True)
class Candidate:
    request: MapperInput
    scope: str
    line: int | None = None
    observed_value: str | None = None

    @property
    def raw_value(self) -> str:
        return (
            self.observed_value
            if self.observed_value is not None
            else self.request.raw_value
        )


def _package(value: str, ecosystem: PackageEcosystem, scope: str) -> Candidate:
    return Candidate(
        MapperInput(source=MapperSource.PACKAGE, raw_value=value, ecosystem=ecosystem),
        scope,
    )


_NPM_ALIAS_TARGET = re.compile(
    r"(?P<name>(?:@[A-Za-z0-9][A-Za-z0-9._~-]*/)?"
    r"[A-Za-z0-9][A-Za-z0-9._~-]*)(?:@[^\r\n]+)?"
)


def _npm_dependency(package: str, specifier: str, scope: str) -> Candidate | None:
    if not specifier.lower().startswith("npm:"):
        return _package(package, PackageEcosystem.NPM, scope)
    target = _NPM_ALIAS_TARGET.fullmatch(specifier[4:])
    if target is None:
        return None
    candidate = _package(target["name"], PackageEcosystem.NPM, scope)
    return Candidate(
        request=candidate.request,
        scope=candidate.scope,
        observed_value=f"{package}@{specifier}",
    )


def _pypi_requirement(value: str, scope: str) -> Candidate:
    match = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?=\s|\[|[<>=!~;@]|$)", value)
    if match is None:
        raise ValueError("unsupported Python dependency declaration")
    remainder = value[match.end() :].strip()
    if remainder and remainder[0] not in "[<>=!~;@(":
        raise ValueError("unsupported Python dependency declaration")
    if re.search(r"(?:===|==|!=|<=|>=|~=|<|>)\s*$", remainder):
        raise ValueError("incomplete Python version specifier")
    return _package(match[1], PackageEcosystem.PYPI, scope)


def _is_pip_url_requirement(value: str) -> bool:
    """Recognize pip VCS/archive URLs without assigning their package identity."""
    vcs_url = (
        r"(?:git\+(?:file|https?|ssh|git)"
        r"|hg\+(?:file|https?|ssh|static-http)"
        r"|svn(?:\+(?:svn|https?|ssh))?"
        r"|bzr\+(?:https?|ssh|sftp|ftp))://\S+"
        r"|bzr\+lp:\S+"
    )
    url = rf"(?:{vcs_url}|(?:https?|file)://\S+)"
    return re.fullmatch(url, value, flags=re.IGNORECASE) is not None


def _without_comments(text: str) -> str:
    # Keep quoted import specifiers intact, blank comments/templates without moving lines.
    pattern = r"""("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(`(?:\\.|[^`\\])*`|/\*[\s\S]*?\*/|//[^\n]*)"""
    return re.sub(
        pattern,
        lambda match: match[1] if match[1] else re.sub(r"[^\n]", " ", match[0]),
        text,
    )


def _read_javascript_string(text: str, start: int) -> tuple[int, str | None]:
    quote = text[start]
    index = start + 1
    while index < len(text):
        character = text[index]
        if character == "\\":
            if index + 1 >= len(text):
                return len(text), None
            index += 3 if text[index + 1 : index + 3] == "\r\n" else 2
            continue
        if character == quote:
            return index + 1, text[start + 1 : index]
        if character in "\r\n":
            return index, None
        index += 1
    return index, None


def _skip_javascript_line_comment(text: str, start: int) -> int:
    newline = text.find("\n", start + 2)
    return len(text) if newline < 0 else newline


def _skip_javascript_block_comment(text: str, start: int) -> int:
    close = text.find("*/", start + 2)
    return len(text) if close < 0 else close + 2


def _skip_javascript_template_expression(text: str, start: int) -> int:
    depth = 1
    index = start
    while index < len(text) and depth:
        if text.startswith("//", index):
            index = _skip_javascript_line_comment(text, index)
        elif text.startswith("/*", index):
            index = _skip_javascript_block_comment(text, index)
        elif text[index] in "\"'":
            end, _ = _read_javascript_string(text, index)
            index = max(end, index + 1)
        elif text[index] == "`":
            index = _skip_javascript_template(text, index)
        elif text[index] == "{":
            depth += 1
            index += 1
        elif text[index] == "}":
            depth -= 1
            index += 1
        elif text[index] == "\\":
            index += 2
        else:
            index += 1
    return index


def _skip_javascript_template(text: str, start: int) -> int:
    index = start + 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text.startswith("${", index):
            index = _skip_javascript_template_expression(text, index + 2)
        elif text[index] == "`":
            return index + 1
        else:
            index += 1
    return index


def _mask_javascript_non_code(text: str) -> tuple[str, dict[int, str]]:
    characters = list(text)
    strings = {}
    index = 0
    while index < len(text):
        start = index
        if text.startswith("//", index):
            index = _skip_javascript_line_comment(text, index)
        elif text.startswith("/*", index):
            index = _skip_javascript_block_comment(text, index)
        elif text[index] == "`":
            index = _skip_javascript_template(text, index)
        elif text[index] in "\"'":
            index, value = _read_javascript_string(text, index)
            if value is None:
                _blank_non_newlines(characters, start, index)
            else:
                strings[start] = value
                _blank_non_newlines(characters, start + 1, index - 1)
            continue
        else:
            index += 1
            continue
        _blank_non_newlines(characters, start, index)
    return "".join(characters), strings


_JS_IDENTIFIER = r"[A-Za-z_$][A-Za-z0-9_$]*"
_JS_NAMED_BINDINGS = r"\{[^{};]*\}"
_JS_NAMESPACE_BINDING = rf"\*\s+as\s+{_JS_IDENTIFIER}"
_JS_IMPORT_CLAUSE = (
    rf"(?:type\s+)?(?:{_JS_IDENTIFIER}(?:\s*,\s*(?:{_JS_NAMESPACE_BINDING}|"
    rf"{_JS_NAMED_BINDINGS}))?|{_JS_NAMESPACE_BINDING}|{_JS_NAMED_BINDINGS})"
)
_JS_IMPORT = re.compile(
    rf"""(?mx)
    ^[ \t]*import\b
    (?:[ \t\r\n]+{_JS_IMPORT_CLAUSE}[ \t\r\n]+from)?
    [ \t\r\n]*(?P<module_quote>["'])
    """
)
_JS_EXPORT = re.compile(
    rf"""(?mx)
    ^[ \t]*export\b[ \t\r\n]+(?:type[ \t\r\n]+)?
    (?:\*(?:[ \t\r\n]+as[ \t\r\n]+{_JS_IDENTIFIER})?|{_JS_NAMED_BINDINGS})
    [ \t\r\n]+from[ \t\r\n]*(?P<module_quote>["'])
    """
)


def _javascript_static_imports(text: str) -> list[tuple[str, int]]:
    masked, strings = _mask_javascript_non_code(text)
    matches = [*_JS_IMPORT.finditer(masked), *_JS_EXPORT.finditer(masked)]
    matches.sort(key=lambda match: match.start())
    imports = []
    line = 1
    position = 0
    for match in matches:
        line += text.count("\n", position, match.start())
        position = match.start()
        module = strings.get(match.start("module_quote"))
        if module is not None:
            imports.append((module, line))
    return imports


def _blank_non_newlines(characters: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if characters[index] not in "\r\n":
            characters[index] = " "


def _java_text_block_end(text: str, start: int) -> int | None:
    index = start + 3
    while index < len(text) and text[index] in " \t\f":
        index += 1
    if index >= len(text) or text[index] not in "\r\n":
        return None
    index += 2 if text[index : index + 2] == "\r\n" else 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text.startswith('"""', index):
            return index + 3
        else:
            index += 1
    return len(text)


def _without_java_non_code(text: str) -> str:
    characters = list(text)
    index = 0
    while index < len(text):
        start = index
        if text.startswith("//", index):
            index = _skip_javascript_line_comment(text, index)
        elif text.startswith("/*", index):
            index = _skip_javascript_block_comment(text, index)
        elif text.startswith('"""', index):
            end = _java_text_block_end(text, index)
            if end is None:
                index += 1
                continue
            index = end
        elif text[index] in "\"'":
            quote = text[index]
            index += 1
            while index < len(text):
                if text[index] == "\\":
                    index += 2
                elif text[index] == quote:
                    index += 1
                    break
                elif text[index] in "\r\n":
                    break
                else:
                    index += 1
        else:
            index += 1
            continue
        _blank_non_newlines(characters, start, min(index, len(text)))
    return "".join(characters)


def _manifest_candidates(path: str, text: str) -> tuple[list[Candidate], bool]:
    name = PurePosixPath(path).name
    candidates = []
    complete = True
    if name == "package.json":
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("package.json must be an object")
        for scope in (
            "dependencies",
            "devDependencies",
            "peerDependencies",
            "optionalDependencies",
        ):
            dependencies = value.get(scope, {})
            if not isinstance(dependencies, dict) or any(
                not isinstance(v, str) for v in dependencies.values()
            ):
                raise ValueError("package dependencies must be a string-valued object")
            for package, specifier in dependencies.items():
                candidate = _npm_dependency(package, specifier, scope)
                if candidate is None:
                    complete = False
                    continue
                candidates.append(candidate)
    elif name == "requirements.txt":
        for line in text.splitlines():
            declaration = line.strip()
            if declaration.startswith("#"):
                continue
            declaration = re.split(r"\s+#", declaration, maxsplit=1)[0].strip()
            if not declaration:
                continue
            if declaration.startswith("-") or declaration.endswith("\\"):
                complete = False
                continue
            if _is_pip_url_requirement(declaration):
                complete = False
                continue
            candidates.append(_pypi_requirement(declaration, "requirements"))
    elif name == "pyproject.toml":
        value = tomllib.loads(text)
        project = value.get("project", {})
        if not isinstance(project, dict):
            raise ValueError("invalid pyproject project table")
        dependencies = project.get("dependencies", [])
        groups = project.get("optional-dependencies", {})
        if not isinstance(dependencies, list) or not isinstance(groups, dict):
            raise ValueError("invalid pyproject dependencies")
        for scope, declarations in [
            ("project.dependencies", dependencies),
            *[(f"optional:{key}", group) for key, group in groups.items()],
        ]:
            if not isinstance(declarations, list) or any(
                not isinstance(item, str) for item in declarations
            ):
                raise ValueError("invalid pyproject dependency list")
            candidates.extend(_pypi_requirement(item, scope) for item in declarations)
        complete = "dependencies" not in project.get(
            "dynamic", []
        ) and "poetry" not in value.get("tool", {})
    elif name == "pom.xml":
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise ValueError("XML entity declarations are not supported")
        root = ET.fromstring(text)
        for group in root:
            if group.tag.split("}")[-1] != "dependencies":
                continue
            for dep in group:
                fields = {
                    child.tag.split("}")[-1]: (child.text or "").strip()
                    for child in dep
                }
                group_id, artifact_id = fields.get("groupId"), fields.get("artifactId")
                if not group_id or not artifact_id or "${" in group_id + artifact_id:
                    complete = False
                    continue
                candidates.append(
                    _package(
                        f"{group_id}:{artifact_id}",
                        PackageEcosystem.MAVEN,
                        fields.get("scope", "compile"),
                    )
                )
    elif name in {"build.gradle", "build.gradle.kts"}:
        cleaned = _without_comments(text)
        pattern = r"""(?m)^\s*(implementation|api|compileOnly|runtimeOnly|testImplementation|testRuntimeOnly|testCompileOnly|compile|testCompile)\s*\(?\s*["']([^"'\n]+)["']"""
        for match in re.finditer(pattern, cleaned):
            parts = match[2].split(":")
            if len(parts) >= 2 and all(parts[:2]) and "$" not in match[2]:
                candidates.append(
                    _package(":".join(parts[:2]), PackageEcosystem.MAVEN, match[1])
                )
        # Gradle is executable and dependency declarations may be computed or imported.
        complete = False
    else:
        raise NotImplementedError("unsupported manifest")
    return candidates, complete


def _source_candidates(path: str, text: str) -> tuple[list[Candidate], bool]:
    suffix = PurePosixPath(path).suffix.lower()
    language = {
        ".py": "Python",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".mjs": "JavaScript",
        ".cjs": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".java": "Java",
    }.get(suffix)
    if language is None:
        raise NotImplementedError("unsupported source language")
    candidates = [
        Candidate(
            MapperInput(source=MapperSource.GITHUB_LANGUAGE, raw_value=language),
            "source_language",
        )
    ]
    if suffix == ".py":
        tree = ast.parse(text)
        for node in ast.walk(tree):
            names = (
                [item.name for item in node.names]
                if isinstance(node, ast.Import)
                else (
                    [node.module]
                    if isinstance(node, ast.ImportFrom)
                    and node.level == 0
                    and node.module
                    else []
                )
            )
            candidates.extend(
                Candidate(
                    MapperInput(
                        source=MapperSource.IMPORT_PATH,
                        raw_value=name,
                        ecosystem=ImportEcosystem.PYTHON,
                    ),
                    "import",
                    node.lineno,
                )
                for name in names
            )
    else:
        if suffix == ".java":
            cleaned = _without_java_non_code(text)
            pattern = r"(?m)^\s*import\s+(?:static\s+)?([A-Za-z_][A-Za-z0-9_.*]*)\s*;"
            imports = [
                (
                    match[1].removesuffix(".*"),
                    cleaned.count("\n", 0, match.start()) + 1,
                )
                for match in re.finditer(pattern, cleaned)
            ]
            ecosystem = ImportEcosystem.JAVA
        else:
            imports = _javascript_static_imports(text)
            ecosystem = ImportEcosystem.JAVASCRIPT
        for raw_value, line in imports:
            if not raw_value.startswith("."):
                candidates.append(
                    Candidate(
                        MapperInput(
                            source=MapperSource.IMPORT_PATH,
                            raw_value=raw_value,
                            ecosystem=ecosystem,
                        ),
                        "import",
                        line,
                    )
                )
    return candidates, True


def _read_candidates(
    artifact: RepoArtifact, reader: ArtifactReader
) -> tuple[list[Candidate], ArtifactAnalysis]:
    metadata = {
        "path": artifact.path,
        "uri": artifact.uri,
        "content_hash": artifact.content_hash,
        "size_bytes": artifact.size_bytes,
    }
    if artifact.size_bytes > MAX_CONSUMER_ARTIFACT_BYTES:
        return [], ArtifactAnalysis(
            **metadata, status=TrendStatus.FAILED, reason="CONSUMER_BYTE_LIMIT"
        )
    try:
        content = reader.read(artifact.uri, max_bytes=artifact.size_bytes)
    except Exception:  # noqa: BLE001 - no reader failure proves verified parser input.
        return [], ArtifactAnalysis(
            **metadata, status=TrendStatus.FAILED, reason="ARTIFACT_UNAVAILABLE"
        )
    if not isinstance(content, bytes) or len(content) != artifact.size_bytes:
        return [], ArtifactAnalysis(
            **metadata, status=TrendStatus.FAILED, reason="SIZE_MISMATCH"
        )
    if hashlib.sha256(content).hexdigest() != artifact.content_hash:
        return [], ArtifactAnalysis(
            **metadata, status=TrendStatus.FAILED, reason="HASH_MISMATCH"
        )
    try:
        text = content.decode("utf-8-sig")
        candidates, complete = (
            _manifest_candidates
            if artifact.artifact_type is RepoArtifactType.MANIFEST
            else _source_candidates
        )(artifact.path, text)
        return candidates, ArtifactAnalysis(
            **metadata,
            status=TrendStatus.READY if complete else TrendStatus.INSUFFICIENT_DATA,
            reason=None if complete else "STATIC_PARSER_PARTIAL",
        )
    except NotImplementedError:
        return [], ArtifactAnalysis(
            **metadata, status=TrendStatus.NOT_SUPPORTED, reason="UNSUPPORTED_ARTIFACT"
        )
    except (
        UnicodeError,
        ValueError,
        SyntaxError,
        ET.ParseError,
        TypeError,
        RecursionError,
    ):
        return [], ArtifactAnalysis(
            **metadata, status=TrendStatus.FAILED, reason="READ_OR_PARSE_FAILED"
        )


def _combined_status(
    artifacts: list[ArtifactAnalysis], collection_status: RepoCollectionStatus
) -> TrendStatus:
    statuses = {artifact.status for artifact in artifacts}
    if collection_status is RepoCollectionStatus.FAILED:
        return TrendStatus.FAILED
    if TrendStatus.FAILED in statuses:
        return (
            TrendStatus.INSUFFICIENT_DATA
            if statuses & {TrendStatus.READY, TrendStatus.INSUFFICIENT_DATA}
            else TrendStatus.FAILED
        )
    if (
        collection_status is RepoCollectionStatus.PARTIAL
        or TrendStatus.INSUFFICIENT_DATA in statuses
        or not artifacts
    ):
        return TrendStatus.INSUFFICIENT_DATA
    if statuses == {TrendStatus.NOT_SUPPORTED}:
        return TrendStatus.NOT_SUPPORTED
    if TrendStatus.NOT_SUPPORTED in statuses:
        return TrendStatus.INSUFFICIENT_DATA
    return TrendStatus.READY


def analyze_public_batch(
    batch: GitHubRepoSnapshotBatch,
    reader: ArtifactReader,
    mapper: RegistryMapper,
    *,
    include_partial: bool = False,
) -> PublicBatchResult:
    """Preserve partial positive evidence and verified artifact identity per repository."""
    if type(include_partial) is not bool:
        raise ValueError("include_partial must be an explicit boolean")
    allowed = {RepoCollectionStatus.COMPLETE, RepoCollectionStatus.REUSED}
    if include_partial:
        allowed.add(RepoCollectionStatus.PARTIAL)
    if (
        sum(
            artifact.size_bytes
            for record in batch.records
            if record.collection_status in allowed
            for artifact in record.artifacts
        )
        > MAX_CONSUMER_BATCH_BYTES
    ):
        raise ValueError(
            "public batch exceeds consumer byte limit; partition input at caller"
        )
    records = []
    repos_by_tech = defaultdict(set)
    analyzed = 0
    for record in sorted(batch.records, key=lambda item: item.activity_rank):
        observations, unresolved, artifacts = [], [], []
        quality_reasons = (
            ("TREE_SHA_EQUALS_COMMIT_SHA",)
            if record.tree_sha == record.pinned_commit_sha
            else ()
        )
        eligible = record.collection_status in allowed
        exclusion_reasons = (
            ()
            if eligible
            else ("COLLECTION_FAILED_EXCLUDED",)
            if record.collection_status is RepoCollectionStatus.FAILED
            else ("PARTIAL_NOT_SELECTED",)
        )
        seen = set()
        for artifact in record.artifacts:
            if not eligible:
                artifacts.append(
                    ArtifactAnalysis(
                        path=artifact.path,
                        uri=artifact.uri,
                        content_hash=artifact.content_hash,
                        size_bytes=artifact.size_bytes,
                        status=TrendStatus.INSUFFICIENT_DATA,
                        reason="COLLECTION_POLICY_EXCLUDED",
                    )
                )
                continue
            candidates, analysis = _read_candidates(artifact, reader)
            artifacts.append(analysis)
            for candidate in candidates:
                result = mapper.map(candidate.request)
                if result.status is not MatchStatus.MATCHED:
                    unresolved.append(
                        UnresolvedObservation(
                            raw_value=candidate.raw_value,
                            basis=candidate.request.source.value,
                            status=result.status.value,
                            candidates=result.candidates,
                            path=artifact.path,
                            scope=candidate.scope,
                        )
                    )
                    continue
                key = (
                    result.tech_id,
                    candidate.request.source.value,
                    artifact.path,
                    candidate.scope,
                    candidate.raw_value,
                )
                if key in seen:
                    continue
                seen.add(key)
                observations.append(
                    TechnologyObservation(
                        tech_id=result.tech_id,
                        basis=candidate.request.source.value,
                        raw_value=candidate.raw_value,
                        scope=candidate.scope,
                        path=artifact.path,
                        uri=artifact.uri,
                        content_hash=artifact.content_hash,
                        line=candidate.line,
                    )
                )
                repos_by_tech[result.tech_id].add(record.github_repo_id)
        included = eligible and any(
            a.status in {TrendStatus.READY, TrendStatus.INSUFFICIENT_DATA}
            for a in artifacts
        )
        analyzed += included
        if eligible and not included:
            exclusion_reasons = ("NO_SUPPORTED_ARTIFACT_PARSED",)
        status = _combined_status(artifacts, record.collection_status)
        if (unresolved or quality_reasons) and status is TrendStatus.READY:
            status = TrendStatus.INSUFFICIENT_DATA
        records.append(
            PublicRepoResult(
                repo_snapshot_id=record.repo_snapshot_id,
                github_repo_id=record.github_repo_id,
                repo_full_name=record.repo_full_name,
                pinned_commit_sha=record.pinned_commit_sha,
                tree_sha=record.tree_sha,
                activity_metric=record.activity_metric,
                activity_period_start=record.activity_period_start.isoformat(),
                activity_period_end=record.activity_period_end.isoformat(),
                activity_rank=record.activity_rank,
                activity_count=record.activity_count,
                collection_status=record.collection_status.value,
                collection_issues=tuple(
                    issue.value for issue in record.collection_issues
                ),
                tree_truncated=record.tree_truncated,
                observed_tree_entries=record.observed_tree_entries,
                checkpoint_uri=record.checkpoint_uri,
                reused_from_snapshot_id=record.reused_from_snapshot_id,
                eligible=eligible,
                included_in_denominator=included,
                partial_included=eligible
                and record.collection_status is RepoCollectionStatus.PARTIAL,
                exclusion_reasons=exclusion_reasons,
                quality_reasons=quality_reasons,
                status=status,
                observations=tuple(observations),
                unresolved=tuple(unresolved),
                artifacts=tuple(artifacts),
            )
        )
    statuses = {record.status for record in records}
    status = (
        TrendStatus.READY
        if statuses == {TrendStatus.READY}
        else TrendStatus.INSUFFICIENT_DATA
    )
    if statuses == {TrendStatus.FAILED}:
        status = TrendStatus.FAILED
    elif statuses == {TrendStatus.NOT_SUPPORTED}:
        status = TrendStatus.NOT_SUPPORTED
    count = len(records)
    return PublicBatchResult(
        dataset_snapshot_id=batch.dataset_snapshot_id,
        pipeline_run_id=batch.pipeline_run_id,
        collector_version=batch.collector_version,
        collection_policy_version=batch.collection_policy.policy_version,
        generated_at=batch.generated_at.isoformat(),
        registry_version=mapper.registry_version,
        status=status,
        include_partial=include_partial,
        total_repo_count=count,
        eligible_repo_count=sum(record.eligible for record in records),
        sample_repo_count=analyzed,
        analyzed_repo_count=analyzed,
        excluded_repo_count=count - analyzed,
        records=tuple(records),
        technologies=tuple(
            PublicTechnologyCount(
                tech_id=tech_id,
                observed_repo_count=len(repo_ids),
                sample_repo_count=analyzed,
                observation_ratio=len(repo_ids) / analyzed,
                github_repo_ids=tuple(sorted(repo_ids)),
            )
            for tech_id, repo_ids in sorted(repos_by_tech.items())
        ),
    )
