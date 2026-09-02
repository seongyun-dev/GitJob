"""Versioned contract for approved Technology Registry snapshots."""

from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from registry.normalization import normalize_mapping_value

TECHNOLOGY_REGISTRY_SCHEMA_VERSION = "technology-registry/v1"

TechId = Annotated[
    str,
    StringConstraints(
        strict=True,
        max_length=80,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]
RegistryVersion = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^registry-[0-9]{8}\.[1-9][0-9]*$",
    ),
]


class JobDomain(StrEnum):
    BACKEND = "BACKEND"
    FRONTEND = "FRONTEND"
    AI_DATA = "AI_DATA"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    MOBILE = "MOBILE"


class RegistryStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class MappingType(StrEnum):
    ALIAS = "ALIAS"
    PACKAGE = "PACKAGE"
    IMPORT_PATH = "IMPORT_PATH"
    STACKOVERFLOW_TAG = "STACKOVERFLOW_TAG"
    GITHUB_LANGUAGE = "GITHUB_LANGUAGE"


class PackageEcosystem(StrEnum):
    NPM = "NPM"
    PYPI = "PYPI"
    MAVEN = "MAVEN"
    NUGET = "NUGET"


class ImportEcosystem(StrEnum):
    JAVASCRIPT = "JAVASCRIPT"
    PYTHON = "PYTHON"
    JAVA = "JAVA"
    DOTNET = "DOTNET"


class MatchMode(StrEnum):
    EXACT = "EXACT"
    PREFIX = "PREFIX"


_AMBIGUOUS_SHORT_LANGUAGE_ALIASES = frozenset({"c", "r", "go"})
_LOCAL_PROVENANCE_ROOTS = frozenset({"AI", "BE", "FE", "Infra", "docs"})


def _validate_provenance_refs(value: tuple[str, ...]) -> tuple[str, ...]:
    for ref in value:
        if ref != ref.strip():
            raise ValueError("provenance_ref must not have surrounding whitespace")

        parsed = urlsplit(ref)
        if parsed.scheme:
            if (
                parsed.scheme != "https"
                or parsed.hostname is None
                or parsed.path in {"", "/"}
            ):
                raise ValueError("provenance_ref URL must be an absolute HTTPS source")
            continue

        relative_path, separator, fragment = ref.partition("#")
        path_parts = relative_path.split("/")
        if (
            "\\" in relative_path
            or len(path_parts) < 2
            or path_parts[0] not in _LOCAL_PROVENANCE_ROOTS
            or any(part in {"", ".", ".."} for part in path_parts)
            or (separator and not fragment)
        ):
            raise ValueError("provenance_ref must be a repository-relative source file")

    if len(value) != len(set(value)):
        raise ValueError("provenance_refs must not contain duplicates")
    return value


class StrictRegistryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Technology(StrictRegistryModel):
    tech_id: TechId
    display_name: StrictStr
    categories: tuple[JobDomain, ...]
    status: RegistryStatus
    provenance_refs: tuple[StrictStr, ...] = Field(min_length=1)

    @field_validator("display_name")
    @classmethod
    def require_display_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("display_name must not be blank")
        return value

    @field_validator("categories")
    @classmethod
    def require_unique_categories(
        cls,
        value: tuple[JobDomain, ...],
    ) -> tuple[JobDomain, ...]:
        if len(value) != len(set(value)):
            raise ValueError("categories must not contain duplicates")
        return value

    @field_validator("provenance_refs")
    @classmethod
    def require_valid_provenance(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        return _validate_provenance_refs(value)

    @model_validator(mode="after")
    def require_active_categories(self) -> "Technology":
        if self.status is RegistryStatus.ACTIVE and not self.categories:
            raise ValueError("ACTIVE technology requires at least one job domain")
        return self


class TechnologyMapping(StrictRegistryModel):
    tech_id: TechId
    mapping_type: MappingType
    ecosystem: PackageEcosystem | ImportEcosystem | None
    value: StrictStr
    match_mode: MatchMode
    status: RegistryStatus
    provenance_refs: tuple[StrictStr, ...] = Field(min_length=1)

    @field_validator("provenance_refs")
    @classmethod
    def require_valid_provenance(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        return _validate_provenance_refs(value)

    @model_validator(mode="after")
    def validate_source_contract(self) -> "TechnologyMapping":
        if self.mapping_type is MappingType.PACKAGE:
            if not isinstance(self.ecosystem, PackageEcosystem):
                raise ValueError("PACKAGE mapping requires a package ecosystem")
        elif self.mapping_type is MappingType.IMPORT_PATH:
            if not isinstance(self.ecosystem, ImportEcosystem):
                raise ValueError("IMPORT_PATH mapping requires an import ecosystem")
        elif self.ecosystem is not None:
            raise ValueError(
                f"{self.mapping_type.value} mapping must not define ecosystem"
            )

        if (
            self.match_mode is MatchMode.PREFIX
            and self.mapping_type is not MappingType.IMPORT_PATH
        ):
            raise ValueError("PREFIX match_mode is only allowed for IMPORT_PATH")

        normalized_value = normalize_mapping_value(
            self.mapping_type.value,
            self.ecosystem.value if self.ecosystem is not None else None,
            self.value,
        )
        if (
            self.mapping_type is MappingType.ALIAS
            and normalized_value in _AMBIGUOUS_SHORT_LANGUAGE_ALIASES
        ):
            raise ValueError(
                "ambiguous short language must not be registered as an ALIAS"
            )
        return self


class TechnologyRegistry(StrictRegistryModel):
    schema_version: Literal["technology-registry/v1"]
    registry_version: RegistryVersion
    technologies: tuple[Technology, ...]
    mappings: tuple[TechnologyMapping, ...]

    @field_validator("registry_version")
    @classmethod
    def require_real_registry_date(cls, value: str) -> str:
        compact_date = value.removeprefix("registry-").split(".", maxsplit=1)[0]
        try:
            date.fromisoformat(
                f"{compact_date[:4]}-{compact_date[4:6]}-{compact_date[6:8]}"
            )
        except ValueError as exc:
            raise ValueError(
                "registry_version must contain a real calendar date"
            ) from exc
        return value

    @model_validator(mode="after")
    def validate_registry_integrity(self) -> "TechnologyRegistry":
        technologies_by_id: dict[str, Technology] = {}
        for technology in self.technologies:
            if technology.tech_id in technologies_by_id:
                raise ValueError(f"duplicate tech_id: {technology.tech_id}")
            technologies_by_id[technology.tech_id] = technology

        active_mapping_tech_ids: set[str] = set()
        conflict_keys: set[tuple[str, str | None, str]] = set()
        for mapping in self.mappings:
            technology = technologies_by_id.get(mapping.tech_id)
            if technology is None:
                raise ValueError(
                    f"mapping references unknown tech_id: {mapping.tech_id}"
                )
            if (
                mapping.status is RegistryStatus.ACTIVE
                and technology.status is RegistryStatus.DEPRECATED
            ):
                raise ValueError(
                    "ACTIVE mapping cannot target DEPRECATED technology: "
                    f"{mapping.tech_id}"
                )
            if mapping.status is RegistryStatus.ACTIVE:
                active_mapping_tech_ids.add(mapping.tech_id)

            ecosystem = (
                mapping.ecosystem.value if mapping.ecosystem is not None else None
            )
            conflict_key = (
                mapping.mapping_type.value,
                ecosystem,
                normalize_mapping_value(
                    mapping.mapping_type.value,
                    ecosystem,
                    mapping.value,
                ),
            )
            if conflict_key in conflict_keys:
                raise ValueError(f"mapping conflict: {conflict_key}")
            conflict_keys.add(conflict_key)

        missing_active_mappings = sorted(
            technology.tech_id
            for technology in self.technologies
            if technology.status is RegistryStatus.ACTIVE
            and technology.tech_id not in active_mapping_tech_ids
        )
        if missing_active_mappings:
            raise ValueError(
                "ACTIVE technology requires at least one active mapping: "
                + ", ".join(missing_active_mappings)
            )
        return self


def _validate_local_provenance_files(
    registry: TechnologyRegistry,
    repository_root: Path,
) -> None:
    resolved_root = repository_root.resolve()
    for item in (*registry.technologies, *registry.mappings):
        for ref in item.provenance_refs:
            if urlsplit(ref).scheme:
                continue
            relative_path, _, fragment = ref.partition("#")
            source_path = (resolved_root / relative_path).resolve()
            if (
                not source_path.is_relative_to(resolved_root)
                or not source_path.is_file()
            ):
                raise ValueError(f"local provenance source does not exist: {ref}")
            if fragment and fragment not in source_path.read_text(encoding="utf-8"):
                raise ValueError(
                    f"local provenance fragment was not observed in source: {ref}"
                )


def load_registry(
    path: Path,
    *,
    repository_root: Path,
) -> TechnologyRegistry:
    """Validate one Registry snapshot and all repository-local source references."""

    registry = TechnologyRegistry.model_validate_json(path.read_text(encoding="utf-8"))
    _validate_local_provenance_files(registry, repository_root)
    return registry


def registry_json_schema() -> dict[str, object]:
    """Return the canonical JSON Schema representation for v1."""

    return TechnologyRegistry.model_json_schema()
