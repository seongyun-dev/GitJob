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
