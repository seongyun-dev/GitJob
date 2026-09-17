"""Read declared dependencies out of a checked-out repository's manifests.

Imports say what the code touches; manifests say what the project decided to
depend on. Both become facts, but they answer different questions and this
module exists because the second one is what an administrator can act on.

### Why candidates come from here and not from imports

An unmatched import is a class path, not a technology. Registering
`org.junit.jupiter.api.Test` as a candidate is useless, and truncating it to a
package needs a depth that does not exist: `org.springframework.web` is three
segments, `org.springframework.data.redis` is four, `jakarta.persistence` is
two. A manifest entry is already the unit someone would promote.

The manifest also sees what the source never mentions. A JDBC driver, a cache
implementation and a test container are declared and then reached only through
configuration, so no import names them.

### Versions are dropped on purpose

`jjwt-api:0.12.6` and `jjwt-api:0.12.7` are one dependency, not two. Keeping the
version would fragment every count by release. Dropping it also removes the
hardest part of reading a Gradle build: interpolation like
`"org.webjars:webjars-locator-lite:${webjarsLocatorLiteVersion}"` only ever
appears in the version, so the coordinate survives a literal read.

### Nothing here executes the build

`gradle dependencies`, `npm install` and `mvn dependency:list` would each be
remote code execution: these files came from an arbitrary repository on the
internet, and `build.gradle` is a program, not a declaration. Everything below
is static parsing, which is also why the Gradle version catalog is read
directly instead of resolved by Gradle.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

import tomllib

from analysis.parse import walk_files

__all__ = [
    "MANIFEST_PARSER_VERSION",
    "DependencyOccurrence",
    "DependencyReport",
    "ManifestScanner",
    "normalize_coordinate",
    "parse_manifest_bytes",
    "supports_manifest_path",
]

log = logging.getLogger("analysis.manifests")
MANIFEST_PARSER_VERSION = "repository-manifest-parser/v2"

#: Specifier prefixes that name code inside this repository rather than a
#: published package. Unlike the import side, these are explicit markers, so no
#: guessing is involved.
_INTERNAL_NPM_SPECIFIERS = ("workspace:", "file:", "link:", "portal:")

_MAVEN_COORDINATE = re.compile(r"^[A-Za-z0-9_.\-]+:[A-Za-z0-9_.\-]+$")

#: `implementation 'g:a:v'`, `testImplementation("g:a:v")`, and the same wrapped
#: in `platform(...)` or `enforcedPlatform(...)`. The configuration name is
#: captured because a test-only dependency should stay distinguishable.
_GRADLE_STRING_DEPENDENCY = re.compile(
    r"""^\s*(?P<scope>[A-Za-z][A-Za-z0-9_]*)\s*[(\s]\s*
        (?:(?:enforced)?[Pp]latform\s*\(\s*)?
        ['"](?P<value>[^'"]+)['"]""",
    re.VERBOSE,
)
#: `implementation libs.spring.boot` — a version catalog alias, resolved below.
_GRADLE_CATALOG_REFERENCE = re.compile(
    r"^\s*(?P<scope>[A-Za-z][A-Za-z0-9_]*)\s*[(\s]\s*libs\.(?P<alias>[A-Za-z0-9_.]+)"
)
#: `implementation project(':core')` — this repository's own module.
_GRADLE_PROJECT_DEPENDENCY = re.compile(r"\bproject\s*\(")

#: PEP 508, reduced to the part that survives normalization: the name, before
#: any extras, specifier, marker or comment.
_PYPI_REQUIREMENT = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)")

_MAVEN_NAMESPACE = re.compile(r"^\{[^}]*\}")


@dataclass(frozen=True)
class DependencyOccurrence:
    """One declared dependency, and where it was declared.

    `file` and `line` are here for the same reason they are on an import: an L0
    verdict has to point at `build.gradle:16`, not merely assert the fact.
    """

    ecosystem: str
    coordinate: str
    scope: str | None
    file: str
    line: int


@dataclass(frozen=True)
class DependencyReport:
    occurrences: tuple[DependencyOccurrence, ...]
    manifests_read: int
    #: Reason -> count, the way `ParseReport` records them. A repository whose
    #: only manifest failed to parse looks identical to one with no manifest
    #: unless this says otherwise.
    skipped_reasons: dict[str, int] = field(default_factory=dict)

    @property
    def coordinates(self) -> tuple[str, ...]:
        """Distinct `ecosystem:coordinate` pairs, in first-seen order."""
        seen: dict[str, None] = {}
        for item in self.occurrences:
            seen.setdefault(f"{item.ecosystem}:{item.coordinate}", None)
        return tuple(seen)

    def by_ecosystem(self) -> dict[str, int]:
        return dict(Counter(item.ecosystem for item in self.occurrences))


def normalize_coordinate(ecosystem: str, raw: str) -> str | None:
    """The form a candidate is counted and matched under, or `None` if unusable.

    Normalization differs per ecosystem because the registries do. PyPI treats
    `Foo_Bar` and `foo-bar` as one project (PEP 503) and NuGet ignores case,
    while npm names are already lowercase and Maven coordinates are
    case-sensitive.
    """
    value = raw.strip()
    if not value:
        return None
    if ecosystem == "MAVEN":
        return value if _MAVEN_COORDINATE.match(value) else None
    if ecosystem == "NPM":
        return value
    if ecosystem == "PYPI":
        return re.sub(r"[-_.]+", "-", value).lower()
    if ecosystem == "NUGET":
        return value.lower()
    if ecosystem in {"GO", "CARGO", "COMPOSER"}:
        return value.lower() if ecosystem in {"CARGO", "COMPOSER"} else value
    raise ValueError(f"unknown ecosystem {ecosystem!r}")


@dataclass
class ManifestScanner:
    """Reads every manifest in one checked-out tree."""

    #: A manifest is a small file. Anything larger is generated or hostile, and
    #: reading it costs more than the dependency list is worth.
    max_file_bytes: int = 512 * 1024
    max_manifests: int = 500

    def scan(self, root: Path) -> DependencyReport:
        occurrences: list[DependencyOccurrence] = []
        skipped: Counter[str] = Counter()
        manifests_read = 0

        catalog = self._load_version_catalogs(root, skipped)

        for path in walk_files(root):
            reader = self._reader_for(path.name.lower())
            if reader is None:
                continue
            if manifests_read >= self.max_manifests:
                skipped["manifest_limit"] += 1
                continue
            relative = path.relative_to(root).as_posix()
            text = self._read(path, skipped)
            if text is None:
                continue
            try:
                found = reader(text, relative, catalog)
            except Exception as error:  # noqa: BLE001 - one bad manifest is not a failed repository
                log.debug("could not read %s: %s", relative, error)
                skipped["manifest_error"] += 1
                continue
            manifests_read += 1
            occurrences.extend(found)

        return DependencyReport(
            occurrences=tuple(occurrences),
            manifests_read=manifests_read,
            skipped_reasons=dict(skipped),
        )

    def _reader_for(self, name: str):
        if name == "package.json":
            return self._read_package_json
        if name in {"build.gradle", "build.gradle.kts"}:
            return self._read_gradle
        if name == "pom.xml":
            return self._read_pom
        if name == "pyproject.toml":
            return self._read_pyproject
        if name.startswith("requirements") and name.endswith(".txt"):
            return self._read_requirements
        if name.endswith(".csproj") or name == "directory.packages.props":
            return self._read_csproj
        if name == "go.mod":
            return self._read_go_mod
        if name == "cargo.toml":
            return self._read_cargo
        if name == "composer.json":
            return self._read_composer
        return None

    def _read(self, path: Path, skipped: Counter[str]) -> str | None:
        try:
            if path.stat().st_size > self.max_file_bytes:
                skipped["too_large"] += 1
                return None
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped["unreadable"] += 1
            return None

    # -- version catalog ----------------------------------------------------

    def _load_version_catalogs(
        self, root: Path, skipped: Counter[str]
    ) -> dict[str, str]:
        """alias -> `group:artifact` from every `gradle/libs.versions.toml`.

        Gradle turns the TOML key `spring-boot` into the accessor
        `libs.spring.boot`, so the alias is keyed by the accessor form. A
        catalog entry alone is not a dependency: the build has to reference it,
        which is what `_read_gradle` resolves against this map.
        """
        catalog: dict[str, str] = {}
        for path in walk_files(root):
            if path.name.lower() != "libs.versions.toml":
                continue
            text = self._read(path, skipped)
            if text is None:
                continue
            try:
                parsed = tomllib.loads(text)
            except Exception:  # noqa: BLE001
                skipped["manifest_error"] += 1
                continue
            for alias, entry in (parsed.get("libraries") or {}).items():
                coordinate = _catalog_coordinate(entry)
                if coordinate:
                    catalog[alias.replace("-", ".").replace("_", ".")] = coordinate
        return catalog

    # -- readers ------------------------------------------------------------

    def _read_package_json(
        self, text: str, relative: str, _catalog: dict[str, str]
    ) -> list[DependencyOccurrence]:
        document = json.loads(text)
        if not isinstance(document, dict):
            return []
        found: list[DependencyOccurrence] = []
        for section in (
            "dependencies",
            "devDependencies",
            "peerDependencies",
            "optionalDependencies",
        ):
            entries = document.get(section)
            if not isinstance(entries, dict):
                continue
            for name, specifier in entries.items():
                if isinstance(specifier, str) and specifier.startswith(
                    _INTERNAL_NPM_SPECIFIERS
                ):
                    # Another package in this repository, not a published one.
                    continue
                coordinate = normalize_coordinate("NPM", name)
                if coordinate is None:
                    continue
                found.append(
                    DependencyOccurrence(
                        ecosystem="NPM",
                        coordinate=coordinate,
                        scope=section,
                        file=relative,
                        # Anchored to the section, and the name has to be a key:
                        # otherwise `"lint": "oxlint"` in scripts wins.
                        line=_line_of(
                            text,
                            rf'"{re.escape(name)}"\s*:',
                            _section_offset(text, section),
                        ),
                    )
                )
        return found

    def _read_gradle(
        self, text: str, relative: str, catalog: dict[str, str]
    ) -> list[DependencyOccurrence]:
        found: list[DependencyOccurrence] = []
        for number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith(("//", "*", "/*")):
                continue
            if _GRADLE_PROJECT_DEPENDENCY.search(stripped):
                continue

            literal = _GRADLE_STRING_DEPENDENCY.match(line)
            if literal:
                # 'group:artifact' or 'group:artifact:version'; the version is
                # dropped, which is also what makes "${var}" harmless.
                parts = literal.group("value").split(":")
                if len(parts) >= 2:
                    coordinate = normalize_coordinate("MAVEN", ":".join(parts[:2]))
                    if coordinate:
                        found.append(
                            DependencyOccurrence(
                                ecosystem="MAVEN",
                                coordinate=coordinate,
                                scope=literal.group("scope"),
                                file=relative,
                                line=number,
                            )
                        )
                continue

            reference = _GRADLE_CATALOG_REFERENCE.match(line)
            if reference:
                coordinate = catalog.get(reference.group("alias").rstrip("."))
                if coordinate:
                    found.append(
                        DependencyOccurrence(
                            ecosystem="MAVEN",
                            coordinate=coordinate,
                            scope=reference.group("scope"),
                            file=relative,
                            line=number,
                        )
                    )
        return found

    def _read_pom(
        self, text: str, relative: str, _catalog: dict[str, str]
    ) -> list[DependencyOccurrence]:
        root = ElementTree.fromstring(text)
        found: list[DependencyOccurrence] = []
        for dependency in root.iter():
            if _tag(dependency) != "dependency":
                continue
            if _inside_dependency_management(root, dependency):
                # dependencyManagement pins versions for modules that may never
                # declare the dependency. Counting it would report intent as use.
                continue
            group = _child_text(dependency, "groupId")
            artifact = _child_text(dependency, "artifactId")
            if not group or not artifact:
                continue
            if "${" in group or "${" in artifact:
                # Resolving these needs the effective POM, which needs Maven.
                continue
            coordinate = normalize_coordinate("MAVEN", f"{group}:{artifact}")
            if coordinate is None:
                continue
            found.append(
                DependencyOccurrence(
                    ecosystem="MAVEN",
                    coordinate=coordinate,
                    scope=_child_text(dependency, "scope") or "compile",
                    file=relative,
                    line=_line_of(
                        text, rf"<artifactId>\s*{re.escape(artifact)}\s*</artifactId>"
                    ),
                )
            )
        return found

    def _read_requirements(
        self, text: str, relative: str, _catalog: dict[str, str]
    ) -> list[DependencyOccurrence]:
        found: list[DependencyOccurrence] = []
        for number, line in enumerate(text.splitlines(), start=1):
            entry = line.split("#", 1)[0].strip()
            if not entry:
                continue
            if entry.startswith("-"):
                # -r/-c pull in another file this walk already visits; -e and
                # --editable point at this repository's own source.
                continue
            if entry.startswith(("./", "../", "/")):
                raise ValueError(
                    "requirements contain no parseable dependency declaration"
                )
            if "://" in entry:
                continue
            match = _PYPI_REQUIREMENT.match(entry)
            if not match:
                continue
            coordinate = normalize_coordinate("PYPI", match.group("name"))
            if coordinate is None:
                continue
            found.append(
                DependencyOccurrence(
                    ecosystem="PYPI",
                    coordinate=coordinate,
                    # A requirements file is the declaration source, not a
                    # dependency scope.  Keep its path in ``file``; putting
                    # the path in ``scope`` creates an invalid result candidate
                    # for nested files and loses the semantic distinction.
                    scope=None,
                    file=relative,
                    line=number,
                )
            )
        return found

    def _read_pyproject(
        self, text: str, relative: str, _catalog: dict[str, str]
    ) -> list[DependencyOccurrence]:
        document = tomllib.loads(text)
        found: list[DependencyOccurrence] = []

        def add(raw: str, scope: str, *, table_key: bool = False) -> None:
            requirement = raw.strip()
            match = _PYPI_REQUIREMENT.match(requirement)
            if not match:
                return
            coordinate = normalize_coordinate("PYPI", match.group("name"))
            if coordinate is None:
                return
            # The requirement as written beats the bare name, which also appears
            # in `[project] name` and inside URLs. A poetry entry is a table key,
            # so there the name is followed by `=` instead.
            pattern = (
                rf'"?{re.escape(match.group("name"))}"?\s*='
                if table_key
                else re.escape(requirement)
            )
            found.append(
                DependencyOccurrence(
                    ecosystem="PYPI",
                    coordinate=coordinate,
                    scope=scope,
                    file=relative,
                    line=_line_of(text, pattern),
                )
            )

        project = document.get("project") or {}
        for requirement in project.get("dependencies") or []:
            if isinstance(requirement, str):
                add(requirement, "dependencies")
        for extra, requirements in (project.get("optional-dependencies") or {}).items():
            for requirement in requirements or []:
                if isinstance(requirement, str):
                    add(requirement, f"optional:{extra}")

        poetry = (document.get("tool") or {}).get("poetry") or {}
        for section in ("dependencies", "dev-dependencies"):
            for name in poetry.get(section) or {}:
                if name.lower() != "python":
                    add(name, f"poetry:{section}", table_key=True)
        return found

    def _read_csproj(
        self, text: str, relative: str, _catalog: dict[str, str]
    ) -> list[DependencyOccurrence]:
        root = ElementTree.fromstring(text)
        found: list[DependencyOccurrence] = []
        for element in root.iter():
            tag = _tag(element)
            if tag not in {"PackageReference", "GlobalPackageReference"}:
                continue
            # PackageVersion only supplies central version metadata; it has no
            # dependency effect until a project declares PackageReference.
            # Update changes an existing item and cannot establish one alone.
            name = element.get("Include")
            if not name:
                continue
            coordinate = normalize_coordinate("NUGET", name)
            if coordinate is None:
                continue
            found.append(
                DependencyOccurrence(
                    ecosystem="NUGET",
                    coordinate=coordinate,
                    scope=tag,
                    file=relative,
                    line=_line_of(text, re.escape(name)),
                )
            )
        return found

    def _read_go_mod(
        self, text: str, relative: str, _catalog: dict[str, str]
    ) -> list[DependencyOccurrence]:
        found: list[DependencyOccurrence] = []
        in_require = False
        for number, line in enumerate(text.splitlines(), start=1):
            stripped = line.split("//", 1)[0].strip()
            if not stripped:
                continue
            if stripped == "require (":
                in_require = True
                continue
            if in_require and stripped == ")":
                in_require = False
                continue
            entry = stripped
            if stripped.startswith("require "):
                entry = stripped[len("require ") :].strip()
            elif not in_require:
                continue
            coordinate = entry.split()[0] if entry.split() else ""
            if coordinate and "." in coordinate and not coordinate.startswith("./"):
                found.append(
                    DependencyOccurrence("GO", coordinate, "require", relative, number)
                )
        return found

    def _read_cargo(
        self, text: str, relative: str, _catalog: dict[str, str]
    ) -> list[DependencyOccurrence]:
        document = tomllib.loads(text)
        found: list[DependencyOccurrence] = []
        for section in ("dependencies", "dev-dependencies", "build-dependencies"):
            entries = document.get(section) or {}
            if not isinstance(entries, dict):
                continue
            for name, specifier in entries.items():
                if isinstance(specifier, dict) and (
                    specifier.get("path") or specifier.get("workspace")
                ):
                    continue
                coordinate = normalize_coordinate("CARGO", str(name))
                if coordinate:
                    found.append(
                        DependencyOccurrence(
                            "CARGO",
                            coordinate,
                            section,
                            relative,
                            _line_of(text, rf"^\s*{re.escape(str(name))}\s*=", 0),
                        )
                    )
        return found

    def _read_composer(
        self, text: str, relative: str, _catalog: dict[str, str]
    ) -> list[DependencyOccurrence]:
        document = json.loads(text)
        if not isinstance(document, dict):
            return []
        found: list[DependencyOccurrence] = []
        for section in ("require", "require-dev"):
            entries = document.get(section) or {}
            if not isinstance(entries, dict):
                continue
            for name, specifier in entries.items():
                if str(name).lower() == "php" or str(specifier).startswith(
                    ("path:", "./", "../")
                ):
                    continue
                coordinate = normalize_coordinate("COMPOSER", str(name))
                if coordinate:
                    found.append(
                        DependencyOccurrence(
                            "COMPOSER",
                            coordinate,
                            section,
                            relative,
                            _line_of(text, rf'"{re.escape(str(name))}"\s*:'),
                        )
                    )
        return found


def parse_manifest_bytes(
    path: str,
    content: bytes,
    *,
    companion_files: dict[str, bytes] | None = None,
) -> tuple[DependencyOccurrence, ...]:
    """Parse a single in-memory manifest using the checkout scanner's readers.

    Unsupported names return an empty tuple. Oversized content and malformed
    supported manifests raise ``ValueError`` so callers can distinguish absent
    support from a corrupt artifact.
    """
    scanner = ManifestScanner()
    if len(content) > scanner.max_file_bytes:
        raise ValueError("manifest exceeds 512 KiB")
    relative = Path(path.replace("\\", "/")).as_posix()
    reader = scanner._reader_for(Path(relative).name.lower())
    if reader is None:
        return ()
    catalog: dict[str, str] = {}
    for companion_path, companion_content in (companion_files or {}).items():
        if Path(companion_path).name.lower() != "libs.versions.toml":
            continue
        if len(companion_content) > scanner.max_file_bytes:
            raise ValueError("companion manifest exceeds 512 KiB")
        document = tomllib.loads(companion_content.decode("utf-8", "replace"))
        for alias, entry in (document.get("libraries") or {}).items():
            coordinate = _catalog_coordinate(entry)
            if coordinate:
                catalog[alias.replace("-", ".").replace("_", ".")] = coordinate
    try:
        return tuple(reader(content.decode("utf-8", "replace"), relative, catalog))
    except (
        json.JSONDecodeError,
        tomllib.TOMLDecodeError,
        ElementTree.ParseError,
    ) as invalid:
        raise ValueError(f"malformed manifest {relative}") from invalid


def supports_manifest_path(path: str) -> bool:
    """Whether an empty parse means a supported manifest with no dependencies."""
    return (
        ManifestScanner()._reader_for(Path(path.replace("\\", "/")).name.lower())
        is not None
    )


def _catalog_coordinate(entry: object) -> str | None:
    """A catalog entry is either `"group:artifact:version"` or a table."""
    if isinstance(entry, str):
        parts = entry.split(":")
        return (
            normalize_coordinate("MAVEN", ":".join(parts[:2]))
            if len(parts) >= 2
            else None
        )
    if not isinstance(entry, dict):
        return None
    module = entry.get("module")
    if isinstance(module, str) and ":" in module:
        return normalize_coordinate("MAVEN", ":".join(module.split(":")[:2]))
    group, name = entry.get("group"), entry.get("name")
    if isinstance(group, str) and isinstance(name, str):
        return normalize_coordinate("MAVEN", f"{group}:{name}")
    return None


def _tag(element: ElementTree.Element) -> str:
    """Local name. POM and csproj both carry a default namespace."""
    return _MAVEN_NAMESPACE.sub("", element.tag)


def _child_text(element: ElementTree.Element, name: str) -> str | None:
    for child in element:
        if _tag(child) == name and child.text:
            return child.text.strip()
    return None


def _inside_dependency_management(
    root: ElementTree.Element, target: ElementTree.Element
) -> bool:
    for managed in root.iter():
        if _tag(managed) != "dependencyManagement":
            continue
        for descendant in managed.iter():
            if descendant is target:
                return True
    return False


def _line_of(text: str, pattern: str, start: int = 0) -> int:
    """1-based line of the first match at or after `start`, else line 1.

    The structured parsers above know *what* is declared but not *where*: json,
    tomllib and ElementTree all discard positions. Evidence needs a line for its
    permalink, so the value is found again in the raw text.

    `start` matters more than it looks. A package name appears in `scripts`
    before it appears in `devDependencies` -- `"lint": "oxlint"` comes first in
    a typical package.json -- so a search from the top of the file points the
    permalink at a line that merely mentions the name.
    """
    match = re.search(pattern, text[start:], flags=re.MULTILINE)
    if match is None:
        return 1
    return text.count("\n", 0, start + match.start()) + 1


def _section_offset(text: str, section: str) -> int:
    """Where a JSON key's value begins, so a search can start after it."""
    match = re.search(rf'"{re.escape(section)}"\s*:', text)
    return match.end() if match else 0
