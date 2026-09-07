"""Deterministic, source-qualified matching against one Registry snapshot."""

import re
from collections import defaultdict
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, StrictStr, field_validator, model_validator

from registry.contracts import (
    ImportEcosystem,
    MatchMode,
    PackageEcosystem,
    RegistryStatus,
    TechnologyRegistry,
)
from registry.normalization import import_path_has_prefix, normalize_mapping_value


class MapperSource(StrEnum):
    DISPLAY_NAME = "DISPLAY_NAME"
    ALIAS = "ALIAS"
    PACKAGE = "PACKAGE"
    IMPORT_PATH = "IMPORT_PATH"
    STACKOVERFLOW_TAG = "STACKOVERFLOW_TAG"
    GITHUB_LANGUAGE = "GITHUB_LANGUAGE"


class MatchStatus(StrEnum):
    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


class MapperInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: MapperSource
    raw_value: StrictStr
    context: StrictStr = ""
    ecosystem: PackageEcosystem | ImportEcosystem | None = None

    @field_validator("raw_value")
    @classmethod
    def require_raw_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("raw_value must not be blank")
        return value

    @model_validator(mode="after")
    def validate_ecosystem(self) -> "MapperInput":
        if self.source is MapperSource.PACKAGE and not isinstance(
            self.ecosystem, PackageEcosystem
        ):
            raise ValueError("PACKAGE source requires ecosystem")
        if self.source is MapperSource.IMPORT_PATH and not isinstance(
            self.ecosystem, ImportEcosystem
        ):
            raise ValueError("IMPORT_PATH source requires ecosystem")
        if (
            self.source not in {MapperSource.PACKAGE, MapperSource.IMPORT_PATH}
            and self.ecosystem is not None
        ):
            raise ValueError(f"{self.source.value} source must not define ecosystem")
        return self


class MatchEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    basis: StrictStr
    normalized_value: StrictStr
    matched_values: tuple[StrictStr, ...] = ()
    reason: StrictStr
    context_rule: StrictStr | None = None


class MapperResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: MapperSource
    status: MatchStatus
    tech_id: StrictStr | None
    candidates: tuple[StrictStr, ...]
    registry_version: StrictStr
    evidence: MatchEvidence


_SHORT_LANGUAGE_IDS = frozenset({"c", "r", "go"})
_CONTEXT_SEPARATOR = r"[\s:/()]{0,8}"
_ISOLATED_C_TOKEN = r"(?<![\w+#-])c(?![\w+#-])"
_SHORT_LANGUAGE_CONTEXT = {
    "c": re.compile(
        rf"{_ISOLATED_C_TOKEN}{_CONTEXT_SEPARATOR}(?:programming(?:\s+language)?|language|compiler|언어|개발)\b",
        re.IGNORECASE,
    ),
    "r": re.compile(
        rf"\br\b{_CONTEXT_SEPARATOR}(?:programming(?:\s+language)?|language|statistics?|statistical|tidyverse|언어|통계)\b",
        re.IGNORECASE,
    ),
    "go": re.compile(
        rf"(?:\bgolang\b|\bgo\b{_CONTEXT_SEPARATOR}(?:programming(?:\s+language)?|language|언어|개발)\b)",
        re.IGNORECASE,
    ),
}


class RegistryMapper:
    """Build immutable lookup indices for a validated Registry snapshot."""

    def __init__(self, registry: TechnologyRegistry) -> None:
        self.registry_version = registry.registry_version
        self._display_names: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
        self._exact: defaultdict[tuple[str, str | None, str], list[tuple[str, str]]] = (
            defaultdict(list)
        )
        self._prefix: list[tuple[str, str, str, str]] = []

        active_tech_ids = {
            technology.tech_id
            for technology in registry.technologies
            if technology.status is RegistryStatus.ACTIVE
        }
        self._active_tech_ids = frozenset(active_tech_ids)
        for technology in registry.technologies:
            if technology.tech_id not in active_tech_ids:
                continue
            key = normalize_mapping_value("ALIAS", None, technology.display_name)
            self._display_names[key].append(
                (technology.tech_id, technology.display_name)
            )

        for mapping in registry.mappings:
            if (
                mapping.status is not RegistryStatus.ACTIVE
                or mapping.tech_id not in active_tech_ids
            ):
                continue
            ecosystem = mapping.ecosystem.value if mapping.ecosystem else None
            normalized = normalize_mapping_value(
                mapping.mapping_type.value,
                ecosystem,
                mapping.value,
            )
            if mapping.match_mode is MatchMode.PREFIX:
                self._prefix.append(
                    (ecosystem or "", normalized, mapping.tech_id, mapping.value)
                )
            else:
                self._exact[(mapping.mapping_type.value, ecosystem, normalized)].append(
                    (mapping.tech_id, mapping.value)
                )

    def has_active_technology(self, tech_id: str) -> bool:
        return tech_id in self._active_tech_ids

    def map(self, request: MapperInput) -> MapperResult:
        ecosystem = request.ecosystem.value if request.ecosystem else None
        if request.source is MapperSource.DISPLAY_NAME:
            normalized = normalize_mapping_value("ALIAS", None, request.raw_value)
            matches = self._display_names.get(normalized, [])
        else:
            normalized = normalize_mapping_value(
                request.source.value,
                ecosystem,
                request.raw_value,
            )
            matches = list(
                self._exact.get((request.source.value, ecosystem, normalized), [])
            )
            if request.source is MapperSource.IMPORT_PATH:
                for prefix_ecosystem, prefix, tech_id, matched_value in self._prefix:
                    if prefix_ecosystem == ecosystem and import_path_has_prefix(
                        prefix,
                        request.raw_value,
                        prefix_ecosystem,
                    ):
                        matches.append((tech_id, matched_value))

        candidates = tuple(sorted({tech_id for tech_id, _ in matches}))
        matched_values = tuple(sorted({value for _, value in matches}))
        basis = request.source.value

        if not candidates:
            return MapperResult(
                source=request.source,
                status=MatchStatus.UNKNOWN,
                tech_id=None,
                candidates=(),
                registry_version=self.registry_version,
                evidence=MatchEvidence(
                    basis=basis,
                    normalized_value=normalized,
                    reason="no active Registry entry matched the input",
                ),
            )

        short_language = (
            request.source is MapperSource.DISPLAY_NAME
            and len(candidates) == 1
            and candidates[0] in _SHORT_LANGUAGE_IDS
        )
        if short_language:
            tech_id = candidates[0]
            if not _SHORT_LANGUAGE_CONTEXT[tech_id].search(request.context):
                return MapperResult(
                    source=request.source,
                    status=MatchStatus.AMBIGUOUS,
                    tech_id=None,
                    candidates=candidates,
                    registry_version=self.registry_version,
                    evidence=MatchEvidence(
                        basis=basis,
                        normalized_value=normalized,
                        matched_values=matched_values,
                        reason="short language name lacks explicit programming context",
                        context_rule="SHORT_LANGUAGE_CONTEXT_REQUIRED",
                    ),
                )
            context_rule = "SHORT_LANGUAGE_CONTEXT_CONFIRMED"
        else:
            context_rule = None

        if len(candidates) > 1:
            return MapperResult(
                source=request.source,
                status=MatchStatus.AMBIGUOUS,
                tech_id=None,
                candidates=candidates,
                registry_version=self.registry_version,
                evidence=MatchEvidence(
                    basis=basis,
                    normalized_value=normalized,
                    matched_values=matched_values,
                    reason="multiple active Registry entries matched the input",
                ),
            )

        return MapperResult(
            source=request.source,
            status=MatchStatus.MATCHED,
            tech_id=candidates[0],
            candidates=candidates,
            registry_version=self.registry_version,
            evidence=MatchEvidence(
                basis=basis,
                normalized_value=normalized,
                matched_values=matched_values,
                reason="one active Registry entry matched the input",
                context_rule=context_rule,
            ),
        )
