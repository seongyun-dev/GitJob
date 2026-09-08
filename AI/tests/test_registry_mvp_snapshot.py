from pathlib import Path

from registry.contracts import MappingType, load_registry
from registry.mapper import MapperInput, MapperSource, RegistryMapper

AI_ROOT = Path(__file__).resolve().parents[1]
NEW_PATH = AI_ROOT / "registry/data/technology_registry_20260908_1.json"


def test_snapshot_retains_historical_entries_and_only_reviewed_additions():
    old = load_registry(
        AI_ROOT / "registry/data/technology_registry_v1.json",
        repository_root=AI_ROOT.parent,
    )
    new = load_registry(NEW_PATH, repository_root=AI_ROOT.parent)
    assert old.registry_version == "registry-20260901.1"
    assert new.registry_version == "registry-20260908.1"
    assert new.technologies[: len(old.technologies)] == old.technologies
    assert new.mappings[: len(old.mappings)] == old.mappings
    additions = {
        "html",
        "css",
        "kotlin",
        "aws",
        "linux",
        "sql",
        "django",
        "mysql",
        "rest-api",
        "git",
    }
    assert {t.tech_id for t in new.technologies} - {
        t.tech_id for t in old.technologies
    } == additions
    mapper = RegistryMapper(new)
    for tech_id in additions:
        assert (
            mapper.map(
                MapperInput(source=MapperSource.ALIAS, raw_value=tech_id)
            ).tech_id
            == tech_id
        )
    assert len(new.mappings) - len(old.mappings) == 11
    language_delta = [
        m
        for m in new.mappings[len(old.mappings) :]
        if m.mapping_type is MappingType.GITHUB_LANGUAGE
    ]
    assert [(m.tech_id, m.value) for m in language_delta] == [("python", "Python")]


def test_python_language_mapping_enabled_and_library_not_coerced():
    registry = load_registry(NEW_PATH, repository_root=AI_ROOT.parent)
    mapper = RegistryMapper(registry)
    assert (
        mapper.map(
            MapperInput(source=MapperSource.GITHUB_LANGUAGE, raw_value="Python")
        ).tech_id
        == "python"
    )
    assert (
        mapper.map(
            MapperInput(source=MapperSource.GITHUB_LANGUAGE, raw_value="Django")
        ).tech_id
        is None
    )
