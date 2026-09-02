import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from registry.contracts import (
    RegistryStatus,
    Technology,
    TechnologyRegistry,
    load_registry,
    registry_json_schema,
)
from registry.normalization import (
    import_path_has_prefix,
    normalize_mapping_value,
)

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "data"
    / "contracts"
    / "technology-registry-v1.schema.json"
)


def valid_registry_payload() -> dict[str, object]:
    return {
        "schema_version": "technology-registry/v1",
        "registry_version": "registry-20260901.1",
        "technologies": [
            {
                "tech_id": "react",
                "display_name": "React",
                "categories": ["FRONTEND"],
                "status": "ACTIVE",
                "provenance_refs": ["FE/package.json#react"],
            },
            {
                "tech_id": "legacy-ui",
                "display_name": "Legacy UI",
                "categories": [],
                "status": "DEPRECATED",
                "provenance_refs": ["docs/data/legacy-ui.md"],
            },
        ],
        "mappings": [
            {
                "tech_id": "react",
                "mapping_type": "PACKAGE",
                "ecosystem": "NPM",
                "value": "React",
                "match_mode": "EXACT",
                "status": "ACTIVE",
                "provenance_refs": ["FE/package.json#react"],
            }
        ],
    }


def validate_registry_payload(payload: dict[str, object]) -> TechnologyRegistry:
    return TechnologyRegistry.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    ("mapping_type", "ecosystem", "value", "expected"),
    [
        ("ALIAS", None, "  Node.\u3000js  ", "node. js"),
        ("STACKOVERFLOW_TAG", None, " C# ", "c#"),
        ("GITHUB_LANGUAGE", None, " C++ ", "c++"),
        ("PACKAGE", "NPM", " React-DOM ", "react-dom"),
        ("PACKAGE", "PYPI", " Friendly_Bard.Core ", "friendly-bard-core"),
        ("PACKAGE", "MAVEN", " org.Example:Demo-Core ", "org.Example:Demo-Core"),
        (
            "PACKAGE",
            "NUGET",
            " Microsoft.Extensions.Hosting ",
            "microsoft.extensions.hosting",
        ),
        ("IMPORT_PATH", "JAVASCRIPT", " React/JSX-Runtime ", "React/JSX-Runtime"),
        ("IMPORT_PATH", "PYTHON", " pydantic.fields ", "pydantic.fields"),
        ("IMPORT_PATH", "JAVA", " org.Example.Demo ", "org.Example.Demo"),
        (
            "IMPORT_PATH",
            "DOTNET",
            " Microsoft.Maui.Controls ",
            "Microsoft.Maui.Controls",
        ),
    ],
)
def test_mapping_normalization_is_source_specific(
    mapping_type: str,
    ecosystem: str | None,
    value: str,
    expected: str,
) -> None:
    assert normalize_mapping_value(mapping_type, ecosystem, value) == expected


@pytest.mark.parametrize("value", ["artifact", ":artifact", "group:", "a:b:c"])
def test_maven_package_requires_group_and_artifact(value: str) -> None:
    with pytest.raises(ValueError, match="group:artifact"):
        normalize_mapping_value("PACKAGE", "MAVEN", value)


@pytest.mark.parametrize(
    ("prefix", "candidate", "ecosystem", "expected"),
    [
        ("react", "react", "JAVASCRIPT", True),
        ("react", "react/jsx-runtime", "JAVASCRIPT", True),
        ("react", "react-dom", "JAVASCRIPT", False),
        ("org.foo", "org.foo.bar", "JAVA", True),
        ("org.foo", "org.foobar", "JAVA", False),
        ("pydantic", "pydantic.fields", "PYTHON", True),
        ("Microsoft.Maui", "Microsoft.Maui.Controls", "DOTNET", True),
    ],
)
def test_import_prefix_matches_only_on_ecosystem_segment_boundaries(
    prefix: str,
    candidate: str,
    ecosystem: str,
    expected: bool,
) -> None:
    assert import_path_has_prefix(prefix, candidate, ecosystem) is expected


def test_valid_registry_preserves_multiple_job_domains() -> None:
    payload = valid_registry_payload()
    payload["technologies"][0]["categories"] = [  # type: ignore[index]
        "FRONTEND",
        "BACKEND",
    ]

    registry = validate_registry_payload(payload)

    assert [category.value for category in registry.technologies[0].categories] == [
        "FRONTEND",
        "BACKEND",
    ]


def test_active_technology_requires_at_least_one_job_domain() -> None:
    payload = valid_registry_payload()
    payload["technologies"][0]["categories"] = []  # type: ignore[index]

    with pytest.raises(ValidationError, match="ACTIVE technology requires"):
        validate_registry_payload(payload)


def test_deprecated_technology_may_have_no_job_domain_or_mapping() -> None:
    registry = validate_registry_payload(valid_registry_payload())

    assert registry.technologies[1].categories == ()
    assert all(mapping.tech_id != "legacy-ui" for mapping in registry.mappings)


@pytest.mark.parametrize(
    ("tech_id", "alias"),
    [("c", " C "), ("r", "Ｒ"), ("go", " Go ")],
)
def test_ambiguous_short_language_aliases_are_forbidden_by_contract(
    tech_id: str,
    alias: str,
) -> None:
    payload = valid_registry_payload()
    payload["technologies"][0].update(  # type: ignore[index]
        {"tech_id": tech_id, "display_name": alias.strip()}
    )
    payload["mappings"][0].update(  # type: ignore[index]
        {
            "tech_id": tech_id,
            "mapping_type": "ALIAS",
            "ecosystem": None,
            "value": alias,
        }
    )

    with pytest.raises(ValidationError, match="ambiguous short language"):
        validate_registry_payload(payload)


@pytest.mark.parametrize(
    ("mapping_type", "ecosystem", "match_mode", "expected_error"),
    [
        ("PACKAGE", None, "EXACT", "PACKAGE mapping requires"),
        ("PACKAGE", "PYTHON", "EXACT", "PACKAGE mapping requires"),
        ("IMPORT_PATH", None, "EXACT", "IMPORT_PATH mapping requires"),
        ("IMPORT_PATH", "PYPI", "PREFIX", "IMPORT_PATH mapping requires"),
        ("ALIAS", "NPM", "EXACT", "must not define ecosystem"),
        ("ALIAS", None, "PREFIX", "PREFIX match_mode is only allowed"),
    ],
)
def test_mapping_type_rejects_invalid_ecosystem_or_match_mode(
    mapping_type: str,
    ecosystem: str | None,
    match_mode: str,
    expected_error: str,
) -> None:
    payload = valid_registry_payload()
    mapping = payload["mappings"][0]  # type: ignore[index]
    mapping.update(  # type: ignore[union-attr]
        {
            "mapping_type": mapping_type,
            "ecosystem": ecosystem,
            "match_mode": match_mode,
        }
    )

    with pytest.raises(ValidationError, match=expected_error):
        validate_registry_payload(payload)


@pytest.mark.parametrize(
    ("ecosystem", "value"),
    [
        ("JAVASCRIPT", "/react"),
        ("JAVASCRIPT", "react/"),
        ("JAVASCRIPT", "react//jsx-runtime"),
        ("PYTHON", ".pydantic"),
        ("PYTHON", "pydantic."),
        ("PYTHON", "pydantic. .fields"),
        ("JAVA", "org..example"),
        ("DOTNET", "Microsoft..Maui"),
        ("JAVASCRIPT", "react/ /jsx-runtime"),
    ],
)
def test_import_paths_reject_empty_segments(
    ecosystem: str,
    value: str,
) -> None:
    payload = valid_registry_payload()
    payload["mappings"][0].update(  # type: ignore[index]
        {
            "mapping_type": "IMPORT_PATH",
            "ecosystem": ecosystem,
            "value": value,
            "match_mode": "PREFIX",
        }
    )

    with pytest.raises(ValidationError, match="empty segment"):
        validate_registry_payload(payload)


@pytest.mark.parametrize(
    "provenance_ref",
    ["https://", "x", " x ", "ftp://example.com/source", "../AI/source.py"],
)
def test_provenance_refs_require_https_or_repository_relative_file(
    provenance_ref: str,
) -> None:
    payload = valid_registry_payload()
    payload["mappings"][0]["provenance_refs"] = [  # type: ignore[index]
        provenance_ref
    ]

    with pytest.raises(ValidationError, match="provenance_ref"):
        validate_registry_payload(payload)


def test_registry_loader_rejects_missing_local_provenance_file(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repo"
    observed_file = repository_root / "FE" / "package.json"
    observed_file.parent.mkdir(parents=True)
    observed_file.write_text('{"react": "latest"}', encoding="utf-8")
    payload = valid_registry_payload()
    payload["technologies"] = [payload["technologies"][0]]  # type: ignore[index]
    payload["mappings"][0]["provenance_refs"] = [  # type: ignore[index]
        "AI/does-not-exist.py"
    ]
    snapshot_path = tmp_path / "technology_registry.json"
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="does not exist"):
        load_registry(snapshot_path, repository_root=repository_root)


def test_registry_loader_rejects_unresolved_local_provenance_fragment(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repo"
    observed_file = repository_root / "FE" / "package.json"
    observed_file.parent.mkdir(parents=True)
    observed_file.write_text('{"dependencies": {"react": "latest"}}', encoding="utf-8")
    payload = valid_registry_payload()
    payload["technologies"] = [payload["technologies"][0]]  # type: ignore[index]
    payload["mappings"][0]["provenance_refs"] = [  # type: ignore[index]
        "FE/package.json#not-an-observed-value"
    ]
    snapshot_path = tmp_path / "technology_registry.json"
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="fragment"):
        load_registry(snapshot_path, repository_root=repository_root)


@pytest.mark.parametrize(
    "registry_version",
    [
        "registry-20260230.1",
        "registry-00000000.1",
        "registry-２０２６０９０１.1",
    ],
)
def test_registry_version_requires_a_real_ascii_calendar_date(
    registry_version: str,
) -> None:
    payload = valid_registry_payload()
    payload["registry_version"] = registry_version

    with pytest.raises(ValidationError, match="calendar date|pattern"):
        validate_registry_payload(payload)


def test_python_model_validation_rejects_bytes_for_enum_fields() -> None:
    with pytest.raises(ValidationError):
        Technology.model_validate(
            {
                "tech_id": "react",
                "display_name": "React",
                "categories": (b"FRONTEND",),
                "status": RegistryStatus.ACTIVE,
                "provenance_refs": ("FE/package.json#react",),
            }
        )


def test_mapping_must_reference_an_existing_technology() -> None:
    payload = valid_registry_payload()
    payload["mappings"][0]["tech_id"] = "missing-tech"  # type: ignore[index]

    with pytest.raises(ValidationError, match="unknown tech_id"):
        validate_registry_payload(payload)


def test_active_mapping_cannot_target_deprecated_technology() -> None:
    payload = valid_registry_payload()
    payload["mappings"][0]["tech_id"] = "legacy-ui"  # type: ignore[index]

    with pytest.raises(ValidationError, match="ACTIVE mapping cannot target"):
        validate_registry_payload(payload)


def test_active_technology_requires_an_active_source_qualified_mapping() -> None:
    payload = valid_registry_payload()
    payload["mappings"][0]["status"] = "DEPRECATED"  # type: ignore[index]

    with pytest.raises(ValidationError, match="active mapping"):
        validate_registry_payload(payload)


def test_mapping_conflict_key_ignores_match_mode() -> None:
    payload = valid_registry_payload()
    first_mapping = payload["mappings"][0]  # type: ignore[index]
    first_mapping.update(  # type: ignore[union-attr]
        {
            "mapping_type": "IMPORT_PATH",
            "ecosystem": "JAVASCRIPT",
            "value": "react",
            "match_mode": "EXACT",
        }
    )
    duplicate = deepcopy(first_mapping)
    duplicate["match_mode"] = "PREFIX"
    payload["mappings"].append(duplicate)  # type: ignore[union-attr]

    with pytest.raises(ValidationError, match="mapping conflict"):
        validate_registry_payload(payload)


def test_mapping_conflict_uses_normalized_value() -> None:
    payload = valid_registry_payload()
    duplicate = deepcopy(payload["mappings"][0])  # type: ignore[index]
    duplicate["value"] = " react "
    payload["mappings"].append(duplicate)  # type: ignore[union-attr]

    with pytest.raises(ValidationError, match="mapping conflict"):
        validate_registry_payload(payload)


def test_committed_json_schema_matches_contract_model_exactly() -> None:
    expected_schema = (
        json.dumps(registry_json_schema(), ensure_ascii=False, indent=2) + "\n"
    ).encode()

    assert SCHEMA_PATH.read_bytes() == expected_schema
