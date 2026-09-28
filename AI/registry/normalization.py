"""Deterministic normalization rules for Technology Registry mappings."""

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")
_PYPI_SEPARATOR = re.compile(r"[-_.]+")
_PACKAGE_ECOSYSTEMS = frozenset({"NPM", "PYPI", "MAVEN", "NUGET"})
_IMPORT_DELIMITERS = {
    "JAVASCRIPT": "/",
    "PYTHON": ".",
    "JAVA": ".",
    "DOTNET": ".",
}


#: Characters that end a segment of a package coordinate, per ecosystem.
#:
#: Only Maven and NuGet have real hierarchy. `org.springframework.boot` groups
#: dozens of artifacts and `Microsoft.Maui` prefixes `Microsoft.Maui.Controls`,
#: so a prefix there means something.
#:
#: npm and PyPI names are flat. `-` is an ordinary character inside a single
#: name -- `react-dom`, `kafka-python`, `python-dateutil` -- so treating it as a
#: boundary would let `react` swallow `react-dom`, which is a different package
#: and, in this registry, a different technology. npm keeps `/` because a scope
#: genuinely is a namespace; PyPI has no boundary at all and therefore no
#: usable prefix.
_PACKAGE_BOUNDARIES = {
    "MAVEN": (".", ":", "-"),
    "NUGET": (".",),
    "NPM": ("/",),
    "PYPI": (),
}


def _nfkc_trim(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized:
        raise ValueError("mapping value must not be blank")
    return normalized


def normalize_mapping_value(
    mapping_type: str,
    ecosystem: str | None,
    value: str,
) -> str:
    """Return the comparison key for one source-qualified mapping."""

    normalized = _nfkc_trim(value)

    if mapping_type == "ALIAS":
        return _WHITESPACE.sub(" ", normalized).casefold()
    if mapping_type == "STACKOVERFLOW_TAG":
        return normalized.lower()
    if mapping_type == "GITHUB_LANGUAGE":
        return normalized.casefold()

    if mapping_type == "PACKAGE":
        if ecosystem not in _PACKAGE_ECOSYSTEMS:
            raise ValueError("PACKAGE mapping requires a package ecosystem")
        if ecosystem == "NPM":
            return normalized.lower()
        if ecosystem == "PYPI":
            return _PYPI_SEPARATOR.sub("-", normalized).lower()
        if ecosystem == "NUGET":
            return normalized.casefold()

        parts = normalized.split(":")
        if len(parts) != 2 or not all(part.strip() for part in parts):
            raise ValueError("MAVEN package value must use group:artifact")
        return f"{parts[0].strip()}:{parts[1].strip()}"

    if mapping_type == "IMPORT_PATH":
        if ecosystem not in _IMPORT_DELIMITERS:
            raise ValueError("IMPORT_PATH mapping requires an import ecosystem")
        delimiter = _IMPORT_DELIMITERS[ecosystem]
        if any(not segment.strip() for segment in normalized.split(delimiter)):
            raise ValueError("IMPORT_PATH value must not contain an empty segment")
        return normalized

    raise ValueError(f"unsupported mapping_type: {mapping_type!r}")


def import_path_has_prefix(
    prefix: str,
    candidate: str,
    ecosystem: str,
) -> bool:
    """Match an import prefix only at its ecosystem's segment boundary."""

    delimiter = _IMPORT_DELIMITERS.get(ecosystem)
    if delimiter is None:
        raise ValueError(f"unsupported import ecosystem: {ecosystem!r}")
    normalized_prefix = normalize_mapping_value("IMPORT_PATH", ecosystem, prefix)
    normalized_candidate = normalize_mapping_value(
        "IMPORT_PATH",
        ecosystem,
        candidate,
    )
    return normalized_candidate == normalized_prefix or normalized_candidate.startswith(
        normalized_prefix + delimiter
    )


def package_has_prefix(prefix: str, candidate: str, ecosystem: str) -> bool:
    """Match a package prefix only at its ecosystem's segment boundary.

    The counterpart to `import_path_has_prefix`, and the reason the registry can
    finally use PREFIX for PACKAGE mappings. Before this existed every PACKAGE
    mapping was EXACT, which meant one row per artifact: Spring Boot publishes
    dozens of starters, so `spring-boot-starter-webmvc` was mapped and
    `spring-boot-starter-data-jpa` was not.

    Raises for an ecosystem whose names are flat. Returning False there would be
    the same silence this function exists to remove -- a mapping that never
    matches looks exactly like a technology nobody uses.
    """

    boundaries = _PACKAGE_BOUNDARIES.get(ecosystem)
    if boundaries is None:
        raise ValueError(f"unsupported package ecosystem: {ecosystem!r}")
    if not boundaries:
        raise ValueError(
            f"{ecosystem} package names are flat; use an EXACT mapping instead of a prefix"
        )
    normalized_prefix = normalize_mapping_value("PACKAGE", ecosystem, prefix)
    normalized_candidate = normalize_mapping_value("PACKAGE", ecosystem, candidate)
    if normalized_candidate == normalized_prefix:
        return True
    return any(
        normalized_candidate.startswith(normalized_prefix + boundary)
        for boundary in boundaries
    )
