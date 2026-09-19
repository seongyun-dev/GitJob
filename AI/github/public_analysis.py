"""Consume pinned public snapshots as positive Registry observations, never absence."""

from __future__ import annotations

import ast
import codecs
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol
from urllib.parse import unquote, urlsplit

import tomllib
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)

from analysis import manifests as shared_manifests

SHARED_MANIFEST_PARSER_VERSION = getattr(
    shared_manifests, "MANIFEST_PARSER_VERSION", None
)
parse_manifest_bytes = getattr(shared_manifests, "parse_manifest_bytes", None)
supports_manifest_path = getattr(shared_manifests, "supports_manifest_path", None)
if all(
    item is None
    for item in (
        SHARED_MANIFEST_PARSER_VERSION,
        parse_manifest_bytes,
        supports_manifest_path,
    )
):
    SHARED_MANIFEST_PARSER_VERSION = None
    parse_manifest_bytes = None
    supports_manifest_path = None
elif any(
    item is None
    for item in (
        SHARED_MANIFEST_PARSER_VERSION,
        parse_manifest_bytes,
        supports_manifest_path,
    )
):
    raise RuntimeError("shared manifest parser exports are incomplete")

from github.contracts import (
    GitHubRepoSnapshotBatch,
    GitObjectSha,
    RepoArtifact,
    RepoArtifactType,
    RepoCollectionStatus,
    RepoLanguageMetadata,
)
from registry.contracts import ImportEcosystem, PackageEcosystem
from registry.mapper import MapperInput, MapperSource, MatchStatus, RegistryMapper
from trend.contracts import TrendStatus

PUBLIC_PARSER_VERSION = "c-public-static-observations/v6"
PUBLIC_SCHEMA_VERSION = "c-public-repo-analysis/v2"
PUBLIC_MANIFEST_PARSER_VERSION = (
    SHARED_MANIFEST_PARSER_VERSION or "c-public-embedded-manifest-parser/v5"
)
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


class LanguageAnalysis(OutputModel):
    language: StrictStr
    file_count: StrictInt = Field(gt=0)
    representative_paths: tuple[StrictStr, ...]
    basis: Literal["GITHUB_LANGUAGE"] = "GITHUB_LANGUAGE"
    status: MatchStatus
    tech_id: str | None
    candidates: tuple[str, ...]

    @model_validator(mode="after")
    def validate_mapping_result(self) -> LanguageAnalysis:
        if self.status is MatchStatus.MATCHED:
            if self.tech_id is None or self.candidates != (self.tech_id,):
                raise ValueError("matched language requires one technology identity")
        elif self.tech_id is not None:
            raise ValueError("unresolved language cannot claim a technology identity")
        return self


class PublicRepoResult(OutputModel):
    repo_snapshot_id: str
    github_repo_id: int
    repo_full_name: str
    pinned_commit_sha: str
    selected_commit_sha: GitObjectSha | None = None
    sha_source: (
        Literal[
            "MONTH_EVENT_SHA",
            "CURRENT_DEFAULT_HEAD",
            "HISTORICAL_HEAD_UNAVAILABLE",
        ]
        | None
    ) = None
    monthly_event_sha: GitObjectSha | None = None
    current_default_head: GitObjectSha | None = None
    sha_fallback_reason: str | None = None
    target_period: str | None = None
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
    language_metadata: tuple[RepoLanguageMetadata, ...] = ()
    language_observations: tuple[LanguageAnalysis, ...] = ()
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
        if (
            self.selected_commit_sha is not None
            and self.selected_commit_sha != self.pinned_commit_sha
        ):
            raise ValueError("selected_commit_sha must equal pinned_commit_sha")
        if self.sha_source == "MONTH_EVENT_SHA":
            if (
                self.selected_commit_sha is None
                or self.selected_commit_sha != self.monthly_event_sha
                or self.sha_fallback_reason is not None
            ):
                raise ValueError("MONTH_EVENT_SHA lineage is inconsistent")
        elif self.sha_source == "CURRENT_DEFAULT_HEAD":
            if (
                self.selected_commit_sha is None
                or self.selected_commit_sha != self.current_default_head
                or self.sha_fallback_reason is None
            ):
                raise ValueError("CURRENT_DEFAULT_HEAD lineage is inconsistent")
        elif self.sha_source == "HISTORICAL_HEAD_UNAVAILABLE":
            if (
                self.selected_commit_sha is not None
                or self.current_default_head is not None
                or self.sha_fallback_reason is None
            ):
                raise ValueError("HISTORICAL_HEAD_UNAVAILABLE lineage is inconsistent")
        elif any(
            value is not None
            for value in (
                self.selected_commit_sha,
                self.monthly_event_sha,
                self.current_default_head,
                self.sha_fallback_reason,
            )
        ):
            raise ValueError("commit lineage fields require sha_source")
        language_sources = {
            (item.language, item.file_count, item.representative_paths)
            for item in self.language_metadata
        }
        language_results = {
            (item.language, item.file_count, item.representative_paths)
            for item in self.language_observations
        }
        if self.eligible and (
            language_sources != language_results
            or len(self.language_metadata) != len(self.language_observations)
        ):
            raise ValueError(
                "eligible language analysis must preserve every source entry"
            )
        parsed = any(
            artifact.status in {TrendStatus.READY, TrendStatus.INSUFFICIENT_DATA}
            and artifact.reason != "COLLECTION_POLICY_EXCLUDED"
            for artifact in self.artifacts
        )
        mapped_language = any(
            item.status is MatchStatus.MATCHED for item in self.language_observations
        )
        if self.included_in_denominator != (
            self.eligible and (parsed or mapped_language)
        ):
            raise ValueError(
                "denominator inclusion requires an eligible supported artifact or language"
            )
        if self.collection_status is RepoCollectionStatus.FAILED and self.eligible:
            raise ValueError("FAILED collections cannot be eligible")
        if not self.eligible and (
            self.observations or self.unresolved or self.language_observations
        ):
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
    schema_version: Literal[
        "c-public-repo-analysis/v1", "c-public-repo-analysis/v2"
    ] = PUBLIC_SCHEMA_VERSION
    dataset_snapshot_id: str
    pipeline_run_id: str
    collector_version: str
    collection_policy_version: str
    generated_at: str
    registry_version: str
    parser_version: str = PUBLIC_PARSER_VERSION
    manifest_parser_version: str | None = None
    status: TrendStatus
    include_partial: StrictBool
    denominator_basis: Literal[
        "ELIGIBLE_REPOSITORIES_WITH_PARSED_ARTIFACT",
        "ELIGIBLE_REPOSITORIES_WITH_SUPPORTED_ARTIFACT_OR_LANGUAGE",
    ] = "ELIGIBLE_REPOSITORIES_WITH_SUPPORTED_ARTIFACT_OR_LANGUAGE"
    total_repo_count: StrictInt = Field(ge=0)
    eligible_repo_count: StrictInt = Field(ge=0)
    sample_repo_count: StrictInt = Field(ge=0)
    analyzed_repo_count: StrictInt = Field(ge=0)
    excluded_repo_count: StrictInt = Field(ge=0)
    records: tuple[PublicRepoResult, ...]
    technologies: tuple[PublicTechnologyCount, ...]

    @model_validator(mode="before")
    @classmethod
    def restore_schema_specific_denominator_basis(cls, value):
        if isinstance(value, dict) and "denominator_basis" not in value:
            value = dict(value)
            value["denominator_basis"] = (
                "ELIGIBLE_REPOSITORIES_WITH_PARSED_ARTIFACT"
                if value.get("schema_version") == "c-public-repo-analysis/v1"
                else "ELIGIBLE_REPOSITORIES_WITH_SUPPORTED_ARTIFACT_OR_LANGUAGE"
            )
        return value

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
                for observation in record.language_observations:
                    if observation.status is MatchStatus.MATCHED:
                        assert observation.tech_id is not None
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


_PIP_HASH_OPTION = re.compile(r"(?:^|\s)--hash(?:=|\s+)\S+")


def _requirements_candidates(text: str) -> tuple[list[Candidate], bool]:
    """Recover independent pip declarations without losing valid neighbors."""

    logical_lines: list[str] = []
    continuation: list[str] = []
    complete = True
    for raw_line in text.splitlines():
        declaration = raw_line.strip()
        if not continuation and declaration.startswith("#"):
            continue
        declaration = re.split(r"\s+#", declaration, maxsplit=1)[0].strip()
        if not declaration:
            continue
        if declaration.endswith("\\"):
            continuation.append(declaration[:-1].rstrip())
            continue
        if continuation:
            declaration = " ".join((*continuation, declaration))
            continuation.clear()
        logical_lines.append(declaration)
    if continuation:
        logical_lines.append(" ".join(continuation))
        complete = False

    candidates: list[Candidate] = []
    invalid_declarations = 0
    for declaration in logical_lines:
        without_hashes = _PIP_HASH_OPTION.sub(" ", declaration).strip()
        if not without_hashes:
            complete = False
            continue
        if without_hashes.startswith("-") or _is_pip_url_requirement(without_hashes):
            complete = False
            continue
        try:
            candidates.append(_pypi_requirement(without_hashes, "requirements"))
        except ValueError:
            invalid_declarations += 1
            complete = False

    if invalid_declarations and not candidates:
        raise ValueError("requirements contain no parseable dependency declaration")
    return candidates, complete


def _poetry_candidates(poetry: object) -> tuple[list[Candidate], bool]:
    if not isinstance(poetry, dict):
        raise TypeError("invalid Poetry table")

    candidates: list[Candidate] = []
    complete = True

    def collect(table: object, scope: str) -> None:
        nonlocal complete
        if table is None:
            return
        if not isinstance(table, dict):
            raise TypeError("invalid Poetry dependency table")
        for package, specifier in table.items():
            if not isinstance(package, str) or not isinstance(specifier, (str, dict)):
                complete = False
                continue
            if package.casefold() == "python":
                continue
            try:
                candidates.append(_pypi_requirement(package, scope))
            except ValueError:
                complete = False

    collect(poetry.get("dependencies"), "poetry.dependencies")
    collect(poetry.get("dev-dependencies"), "poetry.dev-dependencies")
    groups = poetry.get("group", {})
    if not isinstance(groups, dict):
        raise TypeError("invalid Poetry group table")
    for group_name, group in groups.items():
        if not isinstance(group_name, str) or not isinstance(group, dict):
            complete = False
            continue
        collect(group.get("dependencies"), f"poetry.group:{group_name}")
    return candidates, complete


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
        candidates, complete = _requirements_candidates(text)
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
        complete = "dependencies" not in project.get("dynamic", [])
        tool = value.get("tool", {})
        if not isinstance(tool, dict):
            raise ValueError("invalid pyproject tool table")
        if "poetry" in tool:
            poetry_candidates, poetry_complete = _poetry_candidates(tool["poetry"])
            candidates.extend(poetry_candidates)
            complete = complete and poetry_complete
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


_NOT_PRELOADED = object()


def _artifact_metadata(artifact: RepoArtifact) -> dict[str, object]:
    return {
        "path": artifact.path,
        "uri": artifact.uri,
        "content_hash": artifact.content_hash,
        "size_bytes": artifact.size_bytes,
    }


def _verified_artifact_content(
    artifact: RepoArtifact, reader: ArtifactReader
) -> bytes | ArtifactAnalysis:
    metadata = _artifact_metadata(artifact)
    if artifact.size_bytes > MAX_CONSUMER_ARTIFACT_BYTES:
        return ArtifactAnalysis(
            **metadata, status=TrendStatus.FAILED, reason="CONSUMER_BYTE_LIMIT"
        )
    try:
        content = reader.read(artifact.uri, max_bytes=artifact.size_bytes)
    except Exception:  # noqa: BLE001 - no reader failure proves verified parser input.
        return ArtifactAnalysis(
            **metadata, status=TrendStatus.FAILED, reason="ARTIFACT_UNAVAILABLE"
        )
    if not isinstance(content, bytes) or len(content) != artifact.size_bytes:
        return ArtifactAnalysis(
            **metadata, status=TrendStatus.FAILED, reason="SIZE_MISMATCH"
        )
    if hashlib.sha256(content).hexdigest() != artifact.content_hash:
        return ArtifactAnalysis(
            **metadata, status=TrendStatus.FAILED, reason="HASH_MISMATCH"
        )
    return content


def _shared_manifest_candidates(
    artifact: RepoArtifact,
    content: bytes,
    companion_files: dict[str, bytes],
) -> tuple[list[Candidate], list[UnresolvedObservation], bool]:
    if (
        parse_manifest_bytes is None
        or supports_manifest_path is None
        or not supports_manifest_path(artifact.path)
    ):
        raise NotImplementedError("shared manifest parser does not support path")
    candidates = []
    unresolved = []
    for occurrence in parse_manifest_bytes(
        artifact.path, content, companion_files=companion_files
    ):
        scope = occurrence.scope or "dependency"
        try:
            ecosystem = PackageEcosystem(occurrence.ecosystem)
        except ValueError:
            unresolved.append(
                UnresolvedObservation(
                    raw_value=occurrence.coordinate,
                    basis=f"PACKAGE:{occurrence.ecosystem}",
                    status="UNSUPPORTED_ECOSYSTEM",
                    candidates=(),
                    path=artifact.path,
                    scope=scope,
                )
            )
            continue
        candidates.append(
            Candidate(
                request=MapperInput(
                    source=MapperSource.PACKAGE,
                    raw_value=occurrence.coordinate,
                    ecosystem=ecosystem,
                ),
                scope=scope,
                line=occurrence.line,
            )
        )
    return candidates, unresolved, not unresolved


def _encode_parse(
    candidates: list[Candidate],
    unresolved: list[UnresolvedObservation],
    analysis: ArtifactAnalysis,
) -> dict[str, Any]:
    return {
        "candidates": [
            {
                "request": candidate.request.model_dump(mode="json"),
                "scope": candidate.scope,
                "line": candidate.line,
                "observed_value": candidate.observed_value,
            }
            for candidate in candidates
        ],
        "unresolved": [item.model_dump(mode="json") for item in unresolved],
        # `uri` is deliberately dropped. The key is the artifact's content and
        # path, so two repositories holding an identical `package.json` share
        # one entry -- which is most of the reuse. Keeping the first
        # repository's URI in it would hand that URI to the second one.
        "analysis": {
            key: value
            for key, value in analysis.model_dump(mode="json").items()
            if key != "uri"
        },
    }


def _decode_parse(
    payload: Mapping[str, Any], artifact: RepoArtifact
) -> tuple[list[Candidate], list[UnresolvedObservation], ArtifactAnalysis]:
    """Rebuild a parse result, or raise so the caller falls back to reading.

    The URI comes from the artifact being analysed, never from the stored
    entry: the entry is shared by every artifact with these bytes at this
    path, and they do not all live in the same repository.
    """

    candidates = [
        Candidate(
            request=MapperInput.model_validate(row["request"]),
            scope=row["scope"],
            line=row["line"],
            observed_value=row["observed_value"],
        )
        for row in payload["candidates"]
    ]
    unresolved = [
        UnresolvedObservation.model_validate(row) for row in payload["unresolved"]
    ]
    return (
        candidates,
        unresolved,
        ArtifactAnalysis.model_validate({**payload["analysis"], "uri": artifact.uri}),
    )


def _read_candidates(
    artifact: RepoArtifact,
    reader: ArtifactReader,
    *,
    companion_files: dict[str, bytes] | None = None,
    preloaded: bytes | ArtifactAnalysis | object = _NOT_PRELOADED,
    cache: Any = None,
) -> tuple[list[Candidate], list[UnresolvedObservation], ArtifactAnalysis]:
    """Parse one artifact, reusing an earlier identical parse when it is safe.

    Without `cache` this is exactly `_parse_candidates`, which is the path every
    caller took before S15P21E102-347. With it, a stored parse is used only when
    Redis returns the entry recorded for this artifact's verified identity *and*
    the durable object has been listed at the same size in this run. Anything
    else -- miss, unreachable Redis, corrupt bytes, an unconfirmed listing --
    reads the artifact and parses it, which is what would have happened anyway.
    """

    if cache is None or preloaded is not _NOT_PRELOADED:
        return _parse_candidates(
            artifact, reader, companion_files=companion_files, preloaded=preloaded
        )
    digest = cache.cache.companion_digest(companion_files)
    stored = cache.cache.lookup(
        content_hash=artifact.content_hash,
        path=artifact.path,
        size_bytes=artifact.size_bytes,
        uri=artifact.uri,
        companion_digest=digest,
        validator=cache.validator,
    )
    if stored is not None:
        try:
            return _decode_parse(stored, artifact)
        except (KeyError, TypeError, ValueError):
            # A decodable-looking entry that this build cannot rebuild is a
            # miss, not a failure: the artifact is still right there.
            cache.cache.metrics.durable_fallback_count += 1
    candidates, unresolved, analysis = _parse_candidates(
        artifact, reader, companion_files=companion_files, preloaded=preloaded
    )
    if analysis.status is not TrendStatus.FAILED:
        # FAILED covers ARTIFACT_UNAVAILABLE and HASH_MISMATCH, which describe
        # the fetch rather than the artifact, so they must not be remembered.
        cache.cache.put(
            content_hash=artifact.content_hash,
            path=artifact.path,
            size_bytes=artifact.size_bytes,
            companion_digest=digest,
            **_encode_parse(candidates, unresolved, analysis),
        )
    return candidates, unresolved, analysis


def _parse_candidates(
    artifact: RepoArtifact,
    reader: ArtifactReader,
    *,
    companion_files: dict[str, bytes] | None = None,
    preloaded: bytes | ArtifactAnalysis | object = _NOT_PRELOADED,
) -> tuple[list[Candidate], list[UnresolvedObservation], ArtifactAnalysis]:
    metadata = _artifact_metadata(artifact)
    verified = (
        _verified_artifact_content(artifact, reader)
        if preloaded is _NOT_PRELOADED
        else preloaded
    )
    if isinstance(verified, ArtifactAnalysis):
        return [], [], verified
    assert isinstance(verified, bytes)
    try:
        text = verified.decode(
            "utf-16"
            if verified.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))
            else "utf-8-sig"
        )
        unresolved: list[UnresolvedObservation] = []
        if artifact.artifact_type is RepoArtifactType.MANIFEST:
            try:
                candidates, complete = _manifest_candidates(artifact.path, text)
            except NotImplementedError:
                candidates, unresolved, complete = _shared_manifest_candidates(
                    artifact, verified, companion_files or {}
                )
            else:
                if (
                    PurePosixPath(artifact.path).name
                    in {"build.gradle", "build.gradle.kts"}
                    and parse_manifest_bytes is not None
                    and supports_manifest_path is not None
                    and supports_manifest_path(artifact.path)
                ):
                    shared, shared_unresolved, _ = _shared_manifest_candidates(
                        artifact, verified, companion_files or {}
                    )
                    candidates.extend(shared)
                    unresolved.extend(shared_unresolved)
                    complete = False
        else:
            candidates, complete = _source_candidates(artifact.path, text)
        reason = (
            "UNSUPPORTED_PACKAGE_ECOSYSTEM"
            if unresolved
            else None
            if complete
            else "STATIC_PARSER_PARTIAL"
        )
        return (
            candidates,
            unresolved,
            ArtifactAnalysis(
                **metadata,
                status=TrendStatus.READY if complete else TrendStatus.INSUFFICIENT_DATA,
                reason=reason,
            ),
        )
    except NotImplementedError:
        return (
            [],
            [],
            ArtifactAnalysis(
                **metadata,
                status=TrendStatus.NOT_SUPPORTED,
                reason="UNSUPPORTED_ARTIFACT",
            ),
        )
    except (
        UnicodeError,
        ValueError,
        SyntaxError,
        ET.ParseError,
        TypeError,
        RecursionError,
    ):
        return (
            [],
            [],
            ArtifactAnalysis(
                **metadata, status=TrendStatus.FAILED, reason="READ_OR_PARSE_FAILED"
            ),
        )


def _combined_status(
    artifacts: list[ArtifactAnalysis],
    languages: list[LanguageAnalysis],
    collection_status: RepoCollectionStatus,
) -> TrendStatus:
    statuses = {artifact.status for artifact in artifacts}
    mapped_language = any(item.status is MatchStatus.MATCHED for item in languages)
    if collection_status is RepoCollectionStatus.FAILED:
        return TrendStatus.FAILED
    if TrendStatus.FAILED in statuses:
        return (
            TrendStatus.INSUFFICIENT_DATA
            if mapped_language
            or statuses & {TrendStatus.READY, TrendStatus.INSUFFICIENT_DATA}
            else TrendStatus.FAILED
        )
    if (
        collection_status is RepoCollectionStatus.PARTIAL
        or TrendStatus.INSUFFICIENT_DATA in statuses
        or (not artifacts and not mapped_language)
    ):
        return TrendStatus.INSUFFICIENT_DATA
    if statuses == {TrendStatus.NOT_SUPPORTED}:
        return (
            TrendStatus.INSUFFICIENT_DATA
            if mapped_language
            else TrendStatus.NOT_SUPPORTED
        )
    if TrendStatus.NOT_SUPPORTED in statuses:
        return TrendStatus.INSUFFICIENT_DATA
    return TrendStatus.READY


def analyze_public_batch(
    batch: GitHubRepoSnapshotBatch,
    reader: ArtifactReader,
    mapper: RegistryMapper,
    *,
    include_partial: bool = False,
    cache: Any = None,
) -> PublicBatchResult:
    """Preserve partial positive evidence and verified artifact identity per repository.

    `cache` is an optional `ArtifactAnalysisCacheContext` (S15P21E102-347). It
    only ever removes work: the directories this batch will touch are listed up
    front so a reused parse can still be shown to exist, and nothing about the
    result depends on Redis being reachable.
    """
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
    if cache is not None:
        # One LISTSTATUS per directory, before the loop rather than inside it:
        # the alternative is asking the NameNode about every artifact, which
        # costs more than the content reads this is meant to avoid.
        cache.preload(
            artifact.uri
            for record in batch.records
            if record.collection_status in allowed
            for artifact in record.artifacts
        )
    for record in sorted(batch.records, key=lambda item: item.activity_rank):
        observations, unresolved, artifacts, languages = [], [], [], []
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
        preloaded_artifacts: dict[str, bytes | ArtifactAnalysis] = {}
        companion_files: dict[str, bytes] = {}
        if eligible and parse_manifest_bytes is not None:
            for artifact in record.artifacts:
                if PurePosixPath(artifact.path).name != "libs.versions.toml":
                    continue
                verified = _verified_artifact_content(artifact, reader)
                preloaded_artifacts[artifact.path] = verified
                if isinstance(verified, bytes):
                    companion_files[artifact.path] = verified
        if eligible:
            for metadata in record.language_metadata:
                result = mapper.map(
                    MapperInput(
                        source=MapperSource.GITHUB_LANGUAGE,
                        raw_value=metadata.language,
                    )
                )
                languages.append(
                    LanguageAnalysis(
                        language=metadata.language,
                        file_count=metadata.file_count,
                        representative_paths=metadata.representative_paths,
                        status=result.status,
                        tech_id=result.tech_id,
                        candidates=result.candidates,
                    )
                )
                if result.status is MatchStatus.MATCHED:
                    assert result.tech_id is not None
                    repos_by_tech[result.tech_id].add(record.github_repo_id)
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
            candidates, parser_unresolved, analysis = _read_candidates(
                artifact,
                reader,
                companion_files=companion_files,
                preloaded=preloaded_artifacts.get(artifact.path, _NOT_PRELOADED),
                cache=cache,
            )
            artifacts.append(analysis)
            unresolved.extend(parser_unresolved)
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
        included = eligible and (
            any(
                a.status in {TrendStatus.READY, TrendStatus.INSUFFICIENT_DATA}
                for a in artifacts
            )
            or any(item.status is MatchStatus.MATCHED for item in languages)
        )
        analyzed += included
        if eligible and not included:
            exclusion_reasons = ("NO_SUPPORTED_ARTIFACT_PARSED",)
        status = _combined_status(artifacts, languages, record.collection_status)
        if (
            unresolved
            or quality_reasons
            or any(item.status is not MatchStatus.MATCHED for item in languages)
        ) and status is TrendStatus.READY:
            status = TrendStatus.INSUFFICIENT_DATA
        records.append(
            PublicRepoResult(
                repo_snapshot_id=record.repo_snapshot_id,
                github_repo_id=record.github_repo_id,
                repo_full_name=record.repo_full_name,
                pinned_commit_sha=record.pinned_commit_sha,
                selected_commit_sha=record.selected_commit_sha,
                sha_source=record.sha_source,
                monthly_event_sha=record.monthly_event_sha,
                current_default_head=record.current_default_head,
                sha_fallback_reason=record.sha_fallback_reason,
                target_period=record.target_period,
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
                language_metadata=record.language_metadata,
                language_observations=tuple(languages),
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
        manifest_parser_version=PUBLIC_MANIFEST_PARSER_VERSION,
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
