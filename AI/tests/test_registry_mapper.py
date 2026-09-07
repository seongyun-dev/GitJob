import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from registry.contracts import TechnologyRegistry, load_registry
from registry.mapper import (
    MapperInput,
    MapperSource,
    MatchStatus,
    RegistryMapper,
)

AI_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = AI_ROOT / "registry" / "data" / "technology_registry_v1.json"


@pytest.fixture
def mapper() -> RegistryMapper:
    registry = load_registry(REGISTRY_PATH, repository_root=AI_ROOT.parent)
    return RegistryMapper(registry)


@pytest.mark.parametrize(
    ("mapper_input", "expected_tech_id", "expected_basis"),
    [
        (
            MapperInput(source=MapperSource.DISPLAY_NAME, raw_value="Python"),
            "python",
            "DISPLAY_NAME",
        ),
        (
            MapperInput(source=MapperSource.ALIAS, raw_value=" c# "),
            "csharp",
            "ALIAS",
        ),
        (
            MapperInput(
                source=MapperSource.PACKAGE,
                ecosystem="NPM",
                raw_value="React",
            ),
            "react",
            "PACKAGE",
        ),
        (
            MapperInput(
                source=MapperSource.STACKOVERFLOW_TAG,
                raw_value="apache-kafka",
            ),
            "apache-kafka",
            "STACKOVERFLOW_TAG",
        ),
        (
            MapperInput(
                source=MapperSource.IMPORT_PATH,
                ecosystem="PYTHON",
                raw_value="fastapi.routing",
            ),
            "fastapi",
            "IMPORT_PATH",
        ),
    ],
)
def test_exact_registry_sources_map_with_traceable_evidence(
    mapper: RegistryMapper,
    mapper_input: MapperInput,
    expected_tech_id: str,
    expected_basis: str,
) -> None:
    result = mapper.map(mapper_input)

    assert result.status is MatchStatus.MATCHED
    assert result.tech_id == expected_tech_id
    assert result.candidates == (expected_tech_id,)
    assert result.evidence.basis == expected_basis
    assert result.evidence.normalized_value
    assert result.registry_version == "registry-20260901.1"


@pytest.mark.parametrize("raw_value", ["C", "R", "Go"])
def test_short_language_display_name_is_not_matched_without_language_context(
    mapper: RegistryMapper,
    raw_value: str,
) -> None:
    result = mapper.map(
        MapperInput(
            source=MapperSource.DISPLAY_NAME,
            raw_value=raw_value,
            context="C·R·Go 데이터 플랫폼 엔지니어",
        )
    )

    assert result.status is MatchStatus.AMBIGUOUS
    assert result.tech_id is None
    assert result.candidates == (raw_value.casefold(),)
    assert result.evidence.context_rule == "SHORT_LANGUAGE_CONTEXT_REQUIRED"


@pytest.mark.parametrize(
    ("raw_value", "context"),
    [
        ("C", "C-level role working with an embedded systems team"),
        ("C", "C++ programming experience"),
        ("C", "C# programming experience"),
        ("C", "Objective-C programming experience"),
        ("R", "R&D role supporting statistical analysis"),
        ("Go", "Go to market role in a programming education company"),
    ],
)
def test_short_language_does_not_use_unrelated_context_words(
    mapper: RegistryMapper,
    raw_value: str,
    context: str,
) -> None:
    result = mapper.map(
        MapperInput(
            source=MapperSource.DISPLAY_NAME,
            raw_value=raw_value,
            context=context,
        )
    )

    assert result.status is MatchStatus.AMBIGUOUS
    assert result.tech_id is None


@pytest.mark.parametrize(
    ("raw_value", "context", "expected_tech_id"),
    [
        ("C", "C programming language and pointer experience", "c"),
        ("R", "R language statistical modelling experience", "r"),
        ("Go", "Golang backend programming experience", "go"),
    ],
)
def test_short_language_display_name_matches_with_explicit_language_context(
    mapper: RegistryMapper,
    raw_value: str,
    context: str,
    expected_tech_id: str,
) -> None:
    result = mapper.map(
        MapperInput(
            source=MapperSource.DISPLAY_NAME,
            raw_value=raw_value,
            context=context,
        )
    )

    assert result.status is MatchStatus.MATCHED
    assert result.tech_id == expected_tech_id
    assert result.evidence.context_rule == "SHORT_LANGUAGE_CONTEXT_CONFIRMED"


def test_unknown_value_preserves_normalized_reason(mapper: RegistryMapper) -> None:
    result = mapper.map(
        MapperInput(
            source=MapperSource.ALIAS,
            raw_value="QuantumDB",
            context="QuantumDB 경험이 있으면 좋습니다.",
        )
    )

    assert result.status is MatchStatus.UNKNOWN
    assert result.tech_id is None
    assert result.candidates == ()
    assert result.evidence.normalized_value == "quantumdb"
    assert result.evidence.reason == "no active Registry entry matched the input"


def test_duplicate_display_name_candidates_are_ambiguous() -> None:
    registry = TechnologyRegistry.model_validate_json(
        json.dumps(
            {
                "schema_version": "technology-registry/v1",
                "registry_version": "registry-20260907.1",
                "technologies": [
                    {
                        "tech_id": "alpha",
                        "display_name": "Shared",
                        "categories": ["BACKEND"],
                        "status": "ACTIVE",
                        "provenance_refs": ["https://example.com/alpha"],
                    },
                    {
                        "tech_id": "beta",
                        "display_name": "Shared",
                        "categories": ["BACKEND"],
                        "status": "ACTIVE",
                        "provenance_refs": ["https://example.com/beta"],
                    },
                ],
                "mappings": [
                    {
                        "tech_id": "alpha",
                        "mapping_type": "ALIAS",
                        "ecosystem": None,
                        "value": "Alpha Alias",
                        "match_mode": "EXACT",
                        "status": "ACTIVE",
                        "provenance_refs": ["https://example.com/alpha"],
                    },
                    {
                        "tech_id": "beta",
                        "mapping_type": "ALIAS",
                        "ecosystem": None,
                        "value": "Beta Alias",
                        "match_mode": "EXACT",
                        "status": "ACTIVE",
                        "provenance_refs": ["https://example.com/beta"],
                    },
                ],
            }
        )
    )

    result = RegistryMapper(registry).map(
        MapperInput(source=MapperSource.DISPLAY_NAME, raw_value="Shared")
    )

    assert result.status is MatchStatus.AMBIGUOUS
    assert result.tech_id is None
    assert result.candidates == ("alpha", "beta")


@pytest.mark.parametrize("raw_value", ["", " ", "\t\n"])
def test_blank_mapper_input_fails_at_the_boundary(raw_value: str) -> None:
    with pytest.raises(ValidationError, match="raw_value must not be blank"):
        MapperInput(source=MapperSource.ALIAS, raw_value=raw_value)


def test_package_source_requires_an_ecosystem() -> None:
    with pytest.raises(ValidationError, match="requires ecosystem"):
        MapperInput(source=MapperSource.PACKAGE, raw_value="react")
