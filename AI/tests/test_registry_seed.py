import json
from pathlib import Path

from registry.contracts import (
    JobDomain,
    MappingType,
    RegistryStatus,
    load_registry,
)
from registry.normalization import normalize_mapping_value

AI_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = AI_ROOT / "registry" / "data" / "technology_registry_v1.json"
JOB_EXPECTED_PATH = AI_ROOT / "job" / "fixtures" / "job_analysis_expected_v1.json"


def load_seed_registry():
    return load_registry(SEED_PATH, repository_root=AI_ROOT.parent)


def test_seed_is_a_valid_approved_registry_snapshot() -> None:
    registry = load_seed_registry()

    assert registry.schema_version == "technology-registry/v1"
    assert registry.registry_version == "registry-20260901.1"
    assert 30 <= len(registry.technologies) <= 50
    assert all(
        technology.status in {RegistryStatus.ACTIVE, RegistryStatus.DEPRECATED}
        for technology in registry.technologies
    )
    assert all(
        mapping.status in {RegistryStatus.ACTIVE, RegistryStatus.DEPRECATED}
        for mapping in registry.mappings
    )


def test_seed_covers_existing_job_contract_matched_anchors() -> None:
    registry = load_seed_registry()
    expected_fixture = json.loads(JOB_EXPECTED_PATH.read_text(encoding="utf-8"))
    expected_matched_ids = {
        case["expected_tech_id"]
        for case in expected_fixture["cases"]
        if case["expected_match_status"] == "MATCHED"
    }

    assert expected_matched_ids <= {
        technology.tech_id for technology in registry.technologies
    }


def test_seed_maps_each_matched_job_fixture_alias_to_expected_technology() -> None:
    registry = load_seed_registry()
    expected_fixture = json.loads(JOB_EXPECTED_PATH.read_text(encoding="utf-8"))
    expected_alias_pairs = {
        (
            normalize_mapping_value("ALIAS", None, case["raw_technology"]),
            case["expected_tech_id"],
        )
        for case in expected_fixture["cases"]
        if case["expected_match_status"] == "MATCHED"
    }
    active_alias_pairs = {
        (
            normalize_mapping_value("ALIAS", None, mapping.value),
            mapping.tech_id,
        )
        for mapping in registry.mappings
        if mapping.mapping_type is MappingType.ALIAS
        and mapping.status is RegistryStatus.ACTIVE
    }

    assert expected_alias_pairs <= active_alias_pairs


def test_seed_uses_confirmed_multiple_job_domain_examples() -> None:
    registry = load_seed_registry()
    categories_by_id = {
        technology.tech_id: set(technology.categories)
        for technology in registry.technologies
    }

    assert categories_by_id["python"] == {JobDomain.BACKEND, JobDomain.AI_DATA}
    assert categories_by_id["postgresql"] == {
        JobDomain.BACKEND,
        JobDomain.AI_DATA,
        JobDomain.INFRASTRUCTURE,
    }
    assert categories_by_id["react"] == {JobDomain.FRONTEND}
    assert categories_by_id["dotnet-maui"] == {JobDomain.MOBILE}


def test_seed_has_representative_mapping_for_every_supported_source_type() -> None:
    registry = load_seed_registry()

    assert {mapping.mapping_type for mapping in registry.mappings} == set(MappingType)


def test_ambiguous_short_language_names_have_no_free_text_alias() -> None:
    registry = load_seed_registry()
    mappings_by_tech_id = {
        tech_id: [
            mapping
            for mapping in registry.mappings
            if mapping.tech_id == tech_id and mapping.status is RegistryStatus.ACTIVE
        ]
        for tech_id in ("c", "r", "go")
    }

    for tech_id, mappings in mappings_by_tech_id.items():
        assert mappings
        assert all(
            mapping.mapping_type is not MappingType.ALIAS for mapping in mappings
        )
        assert any(
            mapping.mapping_type
            in {MappingType.GITHUB_LANGUAGE, MappingType.STACKOVERFLOW_TAG}
            for mapping in mappings
        )
        assert all(
            not (
                mapping.mapping_type is MappingType.ALIAS
                and normalize_mapping_value("ALIAS", None, mapping.value) == tech_id
            )
            for mapping in registry.mappings
        )


def test_display_names_are_not_implicitly_materialized_as_aliases() -> None:
    registry = load_seed_registry()
    mappings_by_id = {
        technology.tech_id: [
            mapping
            for mapping in registry.mappings
            if mapping.tech_id == technology.tech_id
        ]
        for technology in registry.technologies
    }

    assert mappings_by_id["apache-kafka"]
    assert all(
        not (
            mapping.mapping_type is MappingType.ALIAS
            and mapping.value == "Apache Kafka"
        )
        for mapping in mappings_by_id["apache-kafka"]
    )


def test_all_local_provenance_refs_point_to_existing_repository_files() -> None:
    registry = load_seed_registry()
    repository_root = AI_ROOT.parent
    provenance_refs = {
        ref
        for item in (*registry.technologies, *registry.mappings)
        for ref in item.provenance_refs
        if not ref.startswith("https://")
    }

    missing_paths = sorted(
        ref
        for ref in provenance_refs
        if not (repository_root / ref.split("#", maxsplit=1)[0]).is_file()
    )

    assert missing_paths == []


def test_fixture_provenance_fragments_resolve_to_observed_values() -> None:
    registry = load_seed_registry()
    repository_root = AI_ROOT.parent
    fixture_refs = {
        ref
        for item in (*registry.technologies, *registry.mappings)
        for ref in item.provenance_refs
        if "/fixtures/" in ref and "#" in ref
    }

    unresolved_refs = []
    for ref in sorted(fixture_refs):
        relative_path, fragment = ref.split("#", maxsplit=1)
        fixture_text = (repository_root / relative_path).read_text(encoding="utf-8")
        if fragment not in fixture_text:
            unresolved_refs.append(ref)

    assert unresolved_refs == []
