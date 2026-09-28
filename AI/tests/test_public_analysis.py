import hashlib
import json
from pathlib import Path

import pytest

from common.webhdfs import WebHdfsError
from github import public_analysis
from github.contracts import GitHubRepoSnapshotBatch
from github.public_analysis import (
    LocalMirrorArtifactReader,
    PublicBatchResult,
    _manifest_candidates,
    analyze_public_batch,
)
from github.repo_fetch_store import FileArtifactStore
from registry.contracts import TechnologyRegistry
from registry.mapper import RegistryMapper


@pytest.fixture
def mapper():
    return RegistryMapper(
        TechnologyRegistry.model_validate_json(
            Path("registry/data/technology_registry_v1.json").read_text(
                encoding="utf-8"
            )
        )
    )


@pytest.fixture
def all_language_mapper():
    payload = json.loads(
        Path("registry/data/technology_registry_20260911_1.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {
        "C": "c",
        "C++": "cpp",
        "C#": "csharp",
        "Go": "go",
        "Python": "python",
        "Java": "java",
        "Kotlin": "kotlin",
        "JavaScript": "javascript",
        "TypeScript": "typescript",
        "HTML": "html",
        "CSS": "css",
        "SQL": "sql",
    }
    existing = {
        (item["mapping_type"], item["value"])
        for item in payload["mappings"]
        if item["status"] == "ACTIVE"
    }
    for language, tech_id in expected.items():
        if ("GITHUB_LANGUAGE", language) in existing:
            continue
        payload["mappings"].append(
            {
                "tech_id": tech_id,
                "mapping_type": "GITHUB_LANGUAGE",
                "ecosystem": None,
                "value": language,
                "match_mode": "EXACT",
                "status": "ACTIVE",
                "provenance_refs": [
                    "https://github.com/github-linguist/linguist/blob/main/lib/linguist/languages.yml"
                ],
            }
        )
    return RegistryMapper(TechnologyRegistry.model_validate_json(json.dumps(payload)))


def batch_with(
    content, *, path="package.json", artifact_type="MANIFEST", status="COMPLETE"
):
    data = json.loads(Path("github/fixtures/github_repo_snapshot_v1.json").read_text())
    data["records"] = data["records"][:1]
    row = data["records"][0]
    row["collection_status"] = status
    row["collection_issues"] = {
        "PARTIAL": ["FILE_LIMIT_REACHED"],
        "FAILED": ["ARTIFACT_FETCH_FAILED"],
    }.get(status, [])
    row["artifacts"] = [
        {
            "artifact_type": artifact_type,
            "path": path,
            "uri": "hdfs://trusted/artifacts/one",
            "size_bytes": len(content),
            "content_hash": hashlib.sha256(content).hexdigest(),
        }
    ]
    return GitHubRepoSnapshotBatch.model_validate(data)


class Reader:
    def __init__(self, content):
        self.content = content

    def read(self, uri, *, max_bytes):
        assert uri == "hdfs://trusted/artifacts/one"
        return self.content[: max_bytes + 1]


def test_manifest_declared_dependency_not_text_name_and_partial_provenance(mapper):
    content = b'{"description":"fastapi", "dependencies":{"next":"1", "react":"2"}}'
    result = analyze_public_batch(
        batch_with(content, status="PARTIAL"),
        Reader(content),
        mapper,
        include_partial=True,
    )
    record = result.records[0]
    assert record.status == "INSUFFICIENT_DATA"
    assert {o.tech_id for o in record.observations} == {"nextjs", "react"}
    assert record.pinned_commit_sha == "1" * 40
    assert record.collection_status == "PARTIAL"
    assert record.observations[0].content_hash == hashlib.sha256(content).hexdigest()
    assert result.technologies[0].observed_repo_count == 1
    assert result.sample_repo_count == 1
    assert "absent" not in result.model_dump_json().lower()
    assert record.partial_included
    assert record.included_in_denominator


def test_additive_lineage_and_language_metadata_are_preserved_and_analyzed(mapper):
    data = batch_with(b"{}").model_dump(mode="json")
    row = data["records"][0]
    commit = row["pinned_commit_sha"]
    row.update(
        selected_commit_sha=commit,
        sha_source="MONTH_EVENT_SHA",
        monthly_event_sha=commit,
        current_default_head=None,
        sha_fallback_reason=None,
        target_period="2026-08-01/2026-08-31",
        artifacts=[],
        language_metadata=[
            {
                "language": "JavaScript",
                "file_count": 3,
                "representative_paths": ["src/app.py", "tests/test_app.py"],
            },
            {
                "language": "Unmapped Fixture Language",
                "file_count": 1,
                "representative_paths": ["src/app.fixture"],
            },
        ],
    )
    batch = GitHubRepoSnapshotBatch.model_validate(data)

    class NoRead:
        def read(self, uri, *, max_bytes):
            raise AssertionError("language metadata must not read source artifacts")

    result = analyze_public_batch(batch, NoRead(), mapper)
    output = result.records[0]

    assert result.schema_version == "c-public-repo-analysis/v2"
    assert result.parser_version == "c-public-static-observations/v6"
    assert result.denominator_basis == (
        "ELIGIBLE_REPOSITORIES_WITH_SUPPORTED_ARTIFACT_OR_LANGUAGE"
    )
    assert output.selected_commit_sha == output.monthly_event_sha == commit
    assert output.sha_source == "MONTH_EVENT_SHA"
    assert output.target_period == "2026-08-01/2026-08-31"
    assert output.language_metadata == batch.records[0].language_metadata
    assert [item.language for item in output.language_observations] == [
        "JavaScript",
        "Unmapped Fixture Language",
    ]
    assert output.language_observations[0].tech_id == "javascript"
    assert output.language_observations[0].status == "MATCHED"
    assert output.language_observations[1].status == "UNKNOWN"
    assert output.status == "INSUFFICIENT_DATA"
    assert output.included_in_denominator
    assert result.sample_repo_count == 1
    assert result.technologies[0].tech_id == "javascript"


@pytest.mark.parametrize("include_partial,expected_sample", [(False, 0), (True, 1)])
def test_language_only_partial_respects_explicit_opt_in(
    mapper, include_partial, expected_sample
):
    data = batch_with(b"{}", status="PARTIAL").model_dump(mode="json")
    data["records"][0]["artifacts"] = []
    data["records"][0]["language_metadata"] = [
        {
            "language": "JavaScript",
            "file_count": 1,
            "representative_paths": ["app.py"],
        }
    ]
    batch = GitHubRepoSnapshotBatch.model_validate(data)
    result = analyze_public_batch(
        batch, Reader(b""), mapper, include_partial=include_partial
    )

    assert result.sample_repo_count == expected_sample
    assert result.records[0].partial_included is include_partial
    assert bool(result.records[0].language_observations) is include_partial
    assert bool(result.technologies) is include_partial


def test_unmapped_language_alone_is_unresolved_and_not_a_denominator(mapper):
    data = batch_with(b"{}").model_dump(mode="json")
    data["records"][0]["artifacts"] = []
    data["records"][0]["language_metadata"] = [
        {
            "language": "Unmapped Fixture Language",
            "file_count": 2,
            "representative_paths": ["src/app.fixture"],
        }
    ]
    result = analyze_public_batch(
        GitHubRepoSnapshotBatch.model_validate(data), Reader(b""), mapper
    )

    assert result.sample_repo_count == 0
    assert not result.technologies
    assert result.records[0].language_observations[0].status == "UNKNOWN"
    assert result.records[0].status == "INSUFFICIENT_DATA"


def test_all_twelve_a_language_values_use_github_language_mapping(
    all_language_mapper,
):
    expected = {
        "C": "c",
        "C++": "cpp",
        "C#": "csharp",
        "Go": "go",
        "Python": "python",
        "Java": "java",
        "Kotlin": "kotlin",
        "JavaScript": "javascript",
        "TypeScript": "typescript",
        "HTML": "html",
        "CSS": "css",
        "SQL": "sql",
    }
    data = batch_with(b"{}").model_dump(mode="json")
    data["records"][0]["artifacts"] = []
    data["records"][0]["language_metadata"] = [
        {
            "language": language,
            "file_count": 1,
            "representative_paths": [f"src/example-{index}"],
        }
        for index, language in enumerate(expected)
    ]
    result = analyze_public_batch(
        GitHubRepoSnapshotBatch.model_validate(data), Reader(b""), all_language_mapper
    )

    assert result.sample_repo_count == 1
    assert {
        item.language: item.tech_id for item in result.records[0].language_observations
    } == expected
    assert {item.tech_id for item in result.technologies} == set(expected.values())


@pytest.mark.skipif(
    public_analysis.SHARED_MANIFEST_PARSER_VERSION is None,
    reason="shared repository manifest parser is owned by the Rule Pack change",
)
@pytest.mark.parametrize(
    "path,content,basis",
    [
        (
            "go.mod",
            b"module example.test/app\nrequire example.com/lib v1.0.0\n",
            "PACKAGE:GO",
        ),
        ("Cargo.toml", b'[dependencies]\nserde = "1"\n', "PACKAGE:CARGO"),
        (
            "composer.json",
            b'{"require":{"vendor/package":"^1.0"}}',
            "PACKAGE:COMPOSER",
        ),
    ],
)
def test_shared_manifest_ecosystems_remain_explicitly_unresolved(
    mapper, path, content, basis
):
    result = analyze_public_batch(
        batch_with(content, path=path), Reader(content), mapper
    )
    record = result.records[0]

    assert result.manifest_parser_version == "repository-manifest-parser/v2"
    assert record.included_in_denominator
    assert record.status == "INSUFFICIENT_DATA"
    assert record.artifacts[0].reason == "UNSUPPORTED_PACKAGE_ECOSYSTEM"
    assert record.unresolved[0].basis == basis
    assert record.unresolved[0].status == "UNSUPPORTED_ECOSYSTEM"
    assert not record.observations


@pytest.mark.skipif(
    public_analysis.SHARED_MANIFEST_PARSER_VERSION is None,
    reason="shared repository manifest parser is owned by the Rule Pack change",
)
def test_shared_requirements_variant_and_empty_supported_manifest_are_denominators(
    mapper,
):
    content = b"fastapi==0.141.1\n"
    observed = analyze_public_batch(
        batch_with(content, path="requirements-dev.txt"), Reader(content), mapper
    )
    empty = analyze_public_batch(
        batch_with(b"", path="requirements-dev.txt"), Reader(b""), mapper
    )

    assert {item.tech_id for item in observed.records[0].observations} == {"fastapi"}
    assert observed.records[0].artifacts[0].status == "READY"
    assert empty.records[0].artifacts[0].status == "READY"
    assert empty.sample_repo_count == 1
    assert not empty.records[0].observations


@pytest.mark.skipif(
    public_analysis.SHARED_MANIFEST_PARSER_VERSION is None,
    reason="shared repository manifest parser is owned by the Rule Pack change",
)
def test_shared_csproj_parser_distinguishes_unknown_package_from_unsupported_artifact(
    mapper,
):
    content = b'<Project><ItemGroup><PackageReference Include="Example.Package" /></ItemGroup></Project>'
    result = analyze_public_batch(
        batch_with(content, path="src/App.csproj"), Reader(content), mapper
    )
    record = result.records[0]

    assert record.artifacts[0].status == "READY"
    assert record.artifacts[0].reason is None
    assert record.unresolved[0].basis == "PACKAGE"
    assert record.unresolved[0].status == "UNKNOWN"


@pytest.mark.skipif(
    public_analysis.SHARED_MANIFEST_PARSER_VERSION is None,
    reason="shared repository manifest parser is owned by the Rule Pack change",
)
def test_shared_gradle_catalog_companion_resolves_used_dependency(mapper):
    build = b"dependencies {\n    implementation(libs.spring.boot)\n}\n"
    catalog = b"""[versions]\nspring = "3.5.0"\n[libraries]\nspring-boot = { module = "org.springframework.boot:spring-boot-starter-webmvc", version.ref = "spring" }\n"""
    data = batch_with(build, path="build.gradle").model_dump(mode="json")
    data["records"][0]["artifacts"].append(
        {
            "artifact_type": "MANIFEST",
            "path": "gradle/libs.versions.toml",
            "uri": "hdfs://trusted/artifacts/catalog",
            "size_bytes": len(catalog),
            "content_hash": hashlib.sha256(catalog).hexdigest(),
        }
    )

    class MultiReader:
        def read(self, uri, *, max_bytes):
            return {
                "hdfs://trusted/artifacts/one": build,
                "hdfs://trusted/artifacts/catalog": catalog,
            }[uri][: max_bytes + 1]

    result = analyze_public_batch(
        GitHubRepoSnapshotBatch.model_validate(data), MultiReader(), mapper
    )

    assert {item.tech_id for item in result.records[0].observations} == {"spring-boot"}
    assert result.records[0].artifacts[0].status == "INSUFFICIENT_DATA"
    assert result.records[0].artifacts[1].reason == "UNSUPPORTED_ARTIFACT"


def test_language_positive_survives_unavailable_artifact_as_partial(mapper):
    content = b'{"dependencies":{"react":"1"}}'
    data = batch_with(content).model_dump(mode="json")
    data["records"][0]["language_metadata"] = [
        {
            "language": "JavaScript",
            "file_count": 1,
            "representative_paths": ["app.js"],
        }
    ]

    class Unavailable:
        def read(self, uri, *, max_bytes):
            raise OSError("fixture unavailable")

    result = analyze_public_batch(
        GitHubRepoSnapshotBatch.model_validate(data), Unavailable(), mapper
    )

    assert result.sample_repo_count == 1
    assert result.records[0].status == "INSUFFICIENT_DATA"
    assert result.records[0].language_observations[0].tech_id == "javascript"
    assert result.records[0].artifacts[0].reason == "ARTIFACT_UNAVAILABLE"


def test_base_generated_v1_public_result_remains_readable():
    restored = PublicBatchResult.model_validate_json(
        Path("github/fixtures/public_repo_analysis_v1_base_3a4c57c.json").read_bytes()
    )

    assert restored.schema_version == "c-public-repo-analysis/v1"
    assert restored.parser_version == "c-public-static-observations/v4"
    assert restored.denominator_basis == ("ELIGIBLE_REPOSITORIES_WITH_PARSED_ARTIFACT")
    assert restored.manifest_parser_version is None
    assert restored.records[0].selected_commit_sha is None
    assert restored.records[0].language_metadata == ()


def test_npm_alias_uses_registry_target_instead_of_alias_name(mapper):
    content = b'{"dependencies":{"react":"npm:preact@10.0.0"}}'
    result = analyze_public_batch(batch_with(content), Reader(content), mapper)
    record = result.records[0]

    assert not record.observations
    assert record.status == "INSUFFICIENT_DATA"
    assert [item.raw_value for item in record.unresolved] == ["react@npm:preact@10.0.0"]


def test_npm_alias_target_maps_and_preserves_original_declaration(mapper):
    content = b'{"dependencies":{"react18":"npm:react@18.3.1"}}'
    result = analyze_public_batch(batch_with(content), Reader(content), mapper)
    record = result.records[0]

    assert not record.unresolved
    assert len(record.observations) == 1
    observation = record.observations[0]
    assert (observation.tech_id, observation.raw_value, observation.scope) == (
        "react",
        "react18@npm:react@18.3.1",
        "dependencies",
    )
    assert observation.path == "package.json"
    assert observation.uri == "hdfs://trusted/artifacts/one"
    assert observation.content_hash == hashlib.sha256(content).hexdigest()


def test_scoped_npm_alias_target_is_parsed_without_losing_declaration():
    candidates, complete = _manifest_candidates(
        "package.json",
        '{"dependencies":{"angular18":"npm:@angular/core@18.0.0"}}',
    )

    assert complete
    assert len(candidates) == 1
    assert candidates[0].request.raw_value == "@angular/core"
    assert candidates[0].raw_value == "angular18@npm:@angular/core@18.0.0"


@pytest.mark.parametrize("bad_alias", ["npm:", "npm:@angular", "npm:react@"])
def test_malformed_npm_alias_is_partial_without_false_package_observation(
    mapper, bad_alias
):
    content = json.dumps(
        {"dependencies": {"react": bad_alias, "next": "1"}}, separators=(",", ":")
    ).encode()
    result = analyze_public_batch(batch_with(content), Reader(content), mapper)
    record = result.records[0]

    assert record.status == "INSUFFICIENT_DATA"
    assert record.artifacts[0].status == "INSUFFICIENT_DATA"
    assert record.artifacts[0].reason == "STATIC_PARSER_PARTIAL"
    assert {item.tech_id for item in record.observations} == {"nextjs"}
    assert not record.unresolved


@pytest.mark.parametrize("status", ["FAILED", "PARTIAL"])
def test_collection_excluded_records_never_read_artifacts(mapper, status):
    class NoRead:
        def read(self, uri, *, max_bytes):
            raise AssertionError("excluded collection must not be read")

    content = b'{"dependencies":{"react":"1"}}'
    result = analyze_public_batch(batch_with(content, status=status), NoRead(), mapper)
    record = result.records[0]
    assert result.total_repo_count == 1
    assert (
        result.eligible_repo_count
        == result.analyzed_repo_count
        == result.sample_repo_count
        == 0
    )
    assert result.excluded_repo_count == 1
    assert not record.eligible and not record.included_in_denominator
    assert record.exclusion_reasons
    assert record.artifacts[0].content_hash == hashlib.sha256(content).hexdigest()
    assert not record.observations and not result.technologies


def test_failed_collection_stays_excluded_with_partial_opt_in(mapper):
    class NoRead:
        def read(self, uri, *, max_bytes):
            raise AssertionError("FAILED must never be read")

    result = analyze_public_batch(
        batch_with(b"{}", status="FAILED"), NoRead(), mapper, include_partial=True
    )
    assert result.eligible_repo_count == result.sample_repo_count == 0


def test_denominator_excludes_failed_default_partial_and_unobservable_repos(mapper):
    content = b'{"dependencies":{"react":"1"}}'
    original = batch_with(content)
    records = []
    for index, status in enumerate(
        ("COMPLETE", "FAILED", "PARTIAL", "COMPLETE", "COMPLETE"), start=1
    ):
        row = batch_with(content, status=status).records[0]
        changes = {
            "repo_snapshot_id": f"repo-{index}",
            "github_repo_id": index,
            "repo_full_name": f"fixture/repo-{index}",
            "activity_rank": index,
        }
        if index == 4:
            changes["artifacts"] = ()
        if index == 5:
            changes["artifacts"] = (
                row.artifacts[0].model_copy(update={"path": "unknown.lock"}),
            )
        records.append(row.model_copy(update=changes))
    batch = GitHubRepoSnapshotBatch.model_validate(
        original.model_copy(update={"records": tuple(records)}).model_dump(mode="json")
    )
    result = analyze_public_batch(batch, Reader(content), mapper)
    assert (
        result.total_repo_count,
        result.eligible_repo_count,
        result.analyzed_repo_count,
        result.excluded_repo_count,
    ) == (5, 3, 1, 4)
    assert result.sample_repo_count == 1
    assert result.technologies[0].observed_repo_count == 1
    assert result.technologies[0].observation_ratio == 1
    opted = analyze_public_batch(batch, Reader(content), mapper, include_partial=True)
    assert (
        opted.eligible_repo_count,
        opted.analyzed_repo_count,
        opted.excluded_repo_count,
    ) == (4, 2, 3)
    assert (
        opted.technologies[0].observed_repo_count
        == opted.technologies[0].sample_repo_count
        == 2
    )
    assert all(
        0 <= row.observed_repo_count <= row.sample_repo_count
        for row in opted.technologies
    )


def test_partial_consumer_failure_preserves_verified_positive_observation(mapper):
    content = b'{"dependencies":{"react":"1"}}'
    batch = batch_with(content)
    original = batch.records[0]
    broken = original.artifacts[0].model_copy(
        update={"path": "other/package.json", "content_hash": "0" * 64}
    )
    row = original.model_copy(update={"artifacts": (*original.artifacts, broken)})
    result = analyze_public_batch(
        batch.model_copy(update={"records": (row,)}), Reader(content), mapper
    )
    assert result.records[0].status == "INSUFFICIENT_DATA"
    assert result.records[0].included_in_denominator
    assert {observation.tech_id for observation in result.records[0].observations} == {
        "react"
    }
    assert result.sample_repo_count == result.technologies[0].observed_repo_count == 1


def test_reused_complete_snapshot_is_eligible(mapper):
    content = b'{"dependencies":{"react":"1"}}'
    payload = batch_with(content).model_dump(mode="json")
    payload["records"][0].update(
        collection_status="REUSED", reused_from_snapshot_id="previous-complete"
    )
    result = analyze_public_batch(
        GitHubRepoSnapshotBatch.model_validate(payload), Reader(content), mapper
    )
    assert result.eligible_repo_count == result.analyzed_repo_count == 1
    assert result.records[0].reused_from_snapshot_id == "previous-complete"
    assert not result.records[0].partial_included


def test_commit_repeated_as_tree_sha_keeps_positive_but_flags_unverified_lineage(
    mapper,
):
    content = b'{"dependencies":{"react":"1"}}'
    batch = batch_with(content)
    original = batch.records[0]
    row = original.model_copy(update={"tree_sha": original.pinned_commit_sha})
    result = analyze_public_batch(
        batch.model_copy(update={"records": (row,)}), Reader(content), mapper
    )
    assert result.status == result.records[0].status == "INSUFFICIENT_DATA"
    assert result.records[0].quality_reasons == ("TREE_SHA_EQUALS_COMMIT_SHA",)
    assert result.records[0].tree_sha == original.pinned_commit_sha
    assert result.sample_repo_count == 1
    assert result.technologies[0].tech_id == "react"
    assert result.records[0].artifacts[0].status == "READY"


@pytest.mark.parametrize(
    "field",
    [
        "total_repo_count",
        "eligible_repo_count",
        "analyzed_repo_count",
        "sample_repo_count",
        "excluded_repo_count",
    ],
)
def test_serialized_population_must_reconcile(mapper, field):
    content = b'{"dependencies":{"react":"1"}}'
    payload = analyze_public_batch(
        batch_with(content), Reader(content), mapper
    ).model_dump(mode="json")
    payload[field] += 1
    with pytest.raises(ValueError):
        PublicBatchResult.model_validate(payload)


def test_serialized_observation_cannot_exceed_accepted_denominator(mapper):
    content = b'{"dependencies":{"react":"1"}}'
    payload = analyze_public_batch(
        batch_with(content), Reader(content), mapper
    ).model_dump(mode="json")
    payload["technologies"][0]["observed_repo_count"] = 2
    with pytest.raises(ValueError):
        PublicBatchResult.model_validate(payload)


def test_partial_reader_failure_preserves_other_artifact(mapper):
    content = b'{"dependencies":{"react":"1"}}'
    batch = batch_with(content)
    original = batch.records[0]
    unavailable = original.artifacts[0].model_copy(
        update={
            "path": "other/package.json",
            "uri": "hdfs://trusted/artifacts/unavailable",
        }
    )

    class PartialReader:
        def read(self, uri, *, max_bytes):
            if uri.endswith("unavailable"):
                raise WebHdfsError("fixture read failed")
            return content

    row = original.model_copy(update={"artifacts": (*original.artifacts, unavailable)})
    result = analyze_public_batch(
        batch.model_copy(update={"records": (row,)}), PartialReader(), mapper
    )
    assert result.records[0].status == "INSUFFICIENT_DATA"
    assert result.records[0].artifacts[1].reason == "ARTIFACT_UNAVAILABLE"
    assert result.technologies[0].observed_repo_count == result.sample_repo_count == 1


@pytest.mark.parametrize(
    "error", [ValueError("namespace denied"), RuntimeError("reader unavailable")]
)
def test_reader_stage_error_is_unverified_not_a_parser_failure(mapper, error):
    class UnavailableReader:
        def read(self, uri, *, max_bytes):
            raise error

    result = analyze_public_batch(batch_with(b"{}"), UnavailableReader(), mapper)
    assert result.parser_version == "c-public-static-observations/v6"
    assert result.records[0].artifacts[0].reason == "ARTIFACT_UNAVAILABLE"
    assert result.analyzed_repo_count == 0


@pytest.mark.parametrize("actual", [b"changed", b"x"])
def test_corrupted_artifact_never_contributes_observations(mapper, actual):
    content = b'{"dependencies":{"react":"1"}}'
    result = analyze_public_batch(batch_with(content), Reader(actual), mapper)
    assert result.records[0].status == "FAILED"
    assert not result.records[0].observations
    assert result.records[0].artifacts[0].reason in {"SIZE_MISMATCH", "HASH_MISMATCH"}


def test_hash_mismatch_same_size(mapper):
    content = b'{"dependencies":{"react":"1"}}'
    result = analyze_public_batch(
        batch_with(content), Reader(content.replace(b"1", b"2")), mapper
    )
    assert result.records[0].artifacts[0].reason == "HASH_MISMATCH"


@pytest.mark.parametrize(
    "unparsed_requirement",
    [
        b"git+https://example.invalid/custom.git#egg=custom",
        b"git+git://example.invalid/custom.git#egg=custom",
        b"svn+svn://example.invalid/custom#egg=custom",
        b"https://example.invalid/custom-1.0.tar.gz",
    ],
)
def test_requirements_url_entries_preserve_parsed_evidence_as_partial(
    mapper, unparsed_requirement
):
    content = b"fastapi==0.141.1\n" + unparsed_requirement + b"\n"
    result = analyze_public_batch(
        batch_with(content, path="requirements.txt"), Reader(content), mapper
    )
    record = result.records[0]
    assert result.parser_version == "c-public-static-observations/v6"
    assert result.status == record.status == "INSUFFICIENT_DATA"
    assert record.artifacts[0].status == "INSUFFICIENT_DATA"
    assert record.artifacts[0].reason == "STATIC_PARSER_PARTIAL"
    assert not record.unresolved
    assert len(record.observations) == 1
    observation = record.observations[0]
    assert (
        observation.tech_id,
        observation.raw_value,
        observation.basis,
        observation.scope,
    ) == ("fastapi", "fastapi", "PACKAGE", "requirements")
    assert observation.path == "requirements.txt"
    assert observation.uri == "hdfs://trusted/artifacts/one"
    assert observation.content_hash == hashlib.sha256(content).hexdigest()
    assert record.included_in_denominator
    assert result.sample_repo_count == result.analyzed_repo_count == 1
    assert result.technologies[0].github_repo_ids == (record.github_repo_id,)


@pytest.mark.parametrize(
    "content",
    [
        b"git+https://example.invalid/custom.git#egg=custom\nfastapi==0.141.1\n",
        b"fastapi==0.141.1\ngit+https://example.invalid/custom.git#egg=custom\n",
    ],
)
def test_requirements_vcs_before_or_after_package_is_partial(mapper, content):
    result = analyze_public_batch(
        batch_with(content, path="requirements.txt"), Reader(content), mapper
    )
    assert result.records[0].artifacts[0].reason == "STATIC_PARSER_PARTIAL"
    assert {item.tech_id for item in result.records[0].observations} == {"fastapi"}


def test_requirements_full_line_comment_is_ignored(mapper):
    content = b"# checked by operators\nfastapi==0.141.1\n"
    result = analyze_public_batch(
        batch_with(content, path="requirements.txt"), Reader(content), mapper
    )
    assert result.records[0].status == "READY"
    assert {item.tech_id for item in result.records[0].observations} == {"fastapi"}


def test_requirements_hash_continuations_are_fully_recovered(mapper):
    content = (
        b"fastapi==0.141.1 \\\n"
        b"    --hash=sha256:aaaaaaaa \\\n"
        b"    --hash=sha256:bbbbbbbb\n"
        b"pydantic==2.12.5\n"
    )
    result = analyze_public_batch(
        batch_with(content, path="requirements.txt"), Reader(content), mapper
    )

    assert result.records[0].artifacts[0].status == "READY"
    assert {item.tech_id for item in result.records[0].observations} == {
        "fastapi",
        "pydantic",
    }


def test_requirements_preserves_valid_rows_when_one_row_is_unparseable(mapper):
    content = b"fastapi==0.141.1\n../shared-package\npydantic==2.12.5\n"
    result = analyze_public_batch(
        batch_with(content, path="requirements.txt"), Reader(content), mapper
    )

    record = result.records[0]
    assert record.artifacts[0].reason == "STATIC_PARSER_PARTIAL"
    assert {item.tech_id for item in record.observations} == {"fastapi", "pydantic"}


def test_utf16_bom_requirements_is_decoded_before_static_parsing(mapper):
    content = "fastapi==0.141.1\npydantic==2.12.5\n".encode("utf-16")
    result = analyze_public_batch(
        batch_with(content, path="requirements.txt"), Reader(content), mapper
    )

    assert result.records[0].artifacts[0].status == "READY"
    assert {item.tech_id for item in result.records[0].observations} == {
        "fastapi",
        "pydantic",
    }


def test_python_requirement_forms_keep_explicit_package_identity(mapper):
    requirements = b'fastapi [all] (>= 0.100) ; python_version >= "3.10"\n'
    named_url = b"fastapi @ https://example.invalid/pkg.whl\n"
    pyproject = (
        b'[project]\ndependencies=["fastapi @ https://example.invalid/pkg.whl"]\n'
    )
    requirements_result = analyze_public_batch(
        batch_with(requirements, path="requirements.txt"), Reader(requirements), mapper
    )
    pyproject_result = analyze_public_batch(
        batch_with(pyproject, path="pyproject.toml"), Reader(pyproject), mapper
    )
    named_url_result = analyze_public_batch(
        batch_with(named_url, path="requirements.txt"), Reader(named_url), mapper
    )
    assert {item.tech_id for item in requirements_result.records[0].observations} == {
        "fastapi"
    }
    assert {item.tech_id for item in pyproject_result.records[0].observations} == {
        "fastapi"
    }
    assert {item.tech_id for item in named_url_result.records[0].observations} == {
        "fastapi"
    }


def test_poetry_main_dev_group_and_optional_dependencies_are_observed(mapper):
    content = b"""
[tool.poetry.dependencies]
python = ">=3.11"
fastapi = "^0.141"
pydantic = {version = "^2.12", optional = true}

[tool.poetry.dev-dependencies]
fastapi = "^0.141"

[tool.poetry.group.test.dependencies]
pydantic = {version = "^2.12"}
"""
    result = analyze_public_batch(
        batch_with(content, path="pyproject.toml"), Reader(content), mapper
    )

    assert result.records[0].artifacts[0].status == "READY"
    observations = result.records[0].observations
    assert {item.tech_id for item in observations} == {"fastapi", "pydantic"}
    assert {item.scope for item in observations} == {
        "poetry.dependencies",
        "poetry.dev-dependencies",
        "poetry.group:test",
    }


@pytest.mark.parametrize("content", [b"fastapi==\n", b"random input $$$\n"])
def test_malformed_requirement_still_fails_without_observations(mapper, content):
    result = analyze_public_batch(
        batch_with(content, path="requirements.txt"), Reader(content), mapper
    )
    assert result.records[0].status == "FAILED"
    assert result.records[0].artifacts[0].reason == "READ_OR_PARSE_FAILED"
    assert not result.records[0].observations


@pytest.mark.parametrize(
    "path,body,expected",
    [
        ("app.py", b"import fastapi\n# import django\n", {"fastapi"}),
        (
            "app.ts",
            b'// import next from "next";\nimport React from "react";',
            {"typescript", "react"},
        ),
        (
            "App.java",
            b"package demo;\nimport org.springframework.boot.SpringApplication;",
            {"java", "spring-boot"},
        ),
    ],
)
def test_source_positive_language_and_import(mapper, path, body, expected):
    result = analyze_public_batch(
        batch_with(body, path=path, artifact_type="SOURCE"), Reader(body), mapper
    )
    observed = {o.tech_id for o in result.records[0].observations}
    assert observed in (expected, expected | {"python"})
    assert "django" not in observed


@pytest.mark.parametrize(
    "path,body,expected_line",
    [
        (
            "app.ts",
            b'// header\n\nimport {\n  useState,\n  useEffect\n} from "react";',
            3,
        ),
        (
            "app.js",
            b'const before = 1;\nimport React,\n  { useState } from "react";',
            2,
        ),
    ],
)
def test_multiline_javascript_import_preserves_source_provenance(
    mapper, path, body, expected_line
):
    result = analyze_public_batch(
        batch_with(body, path=path, artifact_type="SOURCE"), Reader(body), mapper
    )
    observation = next(
        item for item in result.records[0].observations if item.tech_id == "react"
    )

    assert observation.raw_value == "react"
    assert observation.line == expected_line
    assert observation.path == path
    assert observation.uri == "hdfs://trusted/artifacts/one"
    assert observation.content_hash == hashlib.sha256(body).hexdigest()


@pytest.mark.parametrize(
    "body",
    [
        b'/*\nimport { useState } from "react";\n*/\nexport const x = 1;',
        b'const example = `\nimport { useState } from "react";\n`;',
        b'const importSource = "react";\nconst value = import("react");',
        b'const example = "\\\nimport { useState } from \\"react\\"";',
        b'const pattern = /import React from "react"/;\nexport const x = 1;',
    ],
)
def test_javascript_import_like_non_syntax_is_not_observed(mapper, body):
    result = analyze_public_batch(
        batch_with(body, path="app.ts", artifact_type="SOURCE"),
        Reader(body),
        mapper,
    )

    assert {item.tech_id for item in result.records[0].observations} == {"typescript"}


@pytest.mark.parametrize(
    "body",
    [
        b'import "react";',
        b'import * as React from "react";',
        b'import type React from "react";',
        b'export { useState } from "react";',
        b'export * from "react";',
    ],
)
def test_supported_javascript_static_import_forms_remain_observed(mapper, body):
    result = analyze_public_batch(
        batch_with(body, path="app.ts", artifact_type="SOURCE"),
        Reader(body),
        mapper,
    )

    assert {item.tech_id for item in result.records[0].observations} == {
        "typescript",
        "react",
    }


def test_java_text_block_import_example_is_not_observed(mapper):
    content = (
        b'String example = """\n'
        b"import org.springframework.boot.SpringApplication;\n"
        b'""";'
    )
    result = analyze_public_batch(
        batch_with(content, path="App.java", artifact_type="SOURCE"),
        Reader(content),
        mapper,
    )

    assert {item.tech_id for item in result.records[0].observations} == {"java"}


def test_real_java_import_preserves_source_provenance(mapper):
    content = (
        b"package demo;\n"
        b"import org.springframework.boot.SpringApplication;\n"
        b"class App {}\n"
    )
    result = analyze_public_batch(
        batch_with(content, path="App.java", artifact_type="SOURCE"),
        Reader(content),
        mapper,
    )
    observation = next(
        item for item in result.records[0].observations if item.tech_id == "spring-boot"
    )

    assert observation.raw_value == "org.springframework.boot.SpringApplication"
    assert observation.line == 2
    assert observation.path == "App.java"
    assert observation.content_hash == hashlib.sha256(content).hexdigest()


@pytest.mark.parametrize(
    "path,body", [("unknown.lock", b"react"), ("package.json", b"not-json")]
)
def test_unsupported_or_bad_manifest_preserves_unknown_coverage(mapper, path, body):
    result = analyze_public_batch(batch_with(body, path=path), Reader(body), mapper)
    assert result.records[0].status in {"NOT_SUPPORTED", "FAILED"}
    assert not result.records[0].observations


def test_missing_artifacts_not_analyzed_zero(mapper):
    batch = batch_with(b"x").model_copy(update={"records": ()})
    result = analyze_public_batch(batch, Reader(b"x"), mapper)
    assert result.status == "INSUFFICIENT_DATA"
    assert not result.technologies


def test_complete_with_no_artifact_is_insufficient_not_absence(mapper):
    batch = batch_with(b"x")
    row = batch.records[0].model_copy(update={"artifacts": ()})
    result = analyze_public_batch(
        batch.model_copy(update={"records": (row,)}), Reader(b"x"), mapper
    )
    assert result.records[0].status == "INSUFFICIENT_DATA"
    assert result.analyzed_repo_count == 0
    assert not result.technologies


def test_unknown_dependency_retained_as_unresolved(mapper):
    content = b'{"dependencies":{"not-in-registry":"1"}}'
    result = analyze_public_batch(batch_with(content), Reader(content), mapper)
    assert result.records[0].status == "INSUFFICIENT_DATA"
    assert result.records[0].unresolved[0].raw_value == "not-in-registry"
    assert result.records[0].unresolved[0].status == "UNKNOWN"


@pytest.mark.parametrize(
    "path,content,expected",
    [
        (
            "requirements.txt",
            b"fastapi[all]>=0.100\npydantic==2\n",
            {"fastapi", "pydantic"},
        ),
        (
            "pyproject.toml",
            b'[project]\nname="react"\ndependencies=["fastapi>=0.100"]\n',
            {"fastapi"},
        ),
        (
            "pom.xml",
            b"<project><dependencyManagement><dependencies><dependency><groupId>org.postgresql</groupId><artifactId>postgresql</artifactId></dependency></dependencies></dependencyManagement><dependencies><dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-webmvc</artifactId></dependency></dependencies></project>",
            {"spring-boot"},
        ),
        (
            "build.gradle",
            b"dependencies {\n implementation 'org.springframework.boot:spring-boot-starter-webmvc:4'\n}\n",
            {"spring-boot"},
        ),
    ],
)
def test_supported_manifests_only_declared_dependencies(
    mapper, path, content, expected
):
    result = analyze_public_batch(
        batch_with(content, path=path), Reader(content), mapper
    )
    assert {o.tech_id for o in result.records[0].observations} == expected


def test_gradle_dynamic_is_partial_even_with_observed_literal(mapper):
    content = b"dependencies {\n implementation 'org.springframework.boot:spring-boot-starter-webmvc:4'\n implementation libs.other\n}"
    result = analyze_public_batch(
        batch_with(content, path="build.gradle"), Reader(content), mapper
    )
    assert result.records[0].status == "INSUFFICIENT_DATA"
    assert result.records[0].artifacts[0].reason == "STATIC_PARSER_PARTIAL"
    assert {o.tech_id for o in result.records[0].observations} == {"spring-boot"}


def test_json_description_and_javascript_template_not_technology_evidence(mapper):
    content = b'const example = `\nimport x from "react";\n`;\nexport const x = 1;'
    result = analyze_public_batch(
        batch_with(content, path="index.ts", artifact_type="SOURCE"),
        Reader(content),
        mapper,
    )
    assert {o.tech_id for o in result.records[0].observations} == {"typescript"}


def test_xml_entity_document_fails_without_expanding(mapper):
    content = b'<!DOCTYPE project [<!ENTITY x "react">]><project>&x;</project>'
    result = analyze_public_batch(
        batch_with(content, path="pom.xml"), Reader(content), mapper
    )
    assert result.records[0].status == "FAILED"
    assert not result.records[0].observations


def test_local_mirror_reader_bounds_and_containment(tmp_path):
    (tmp_path / "one").write_bytes(b"hello")
    reader = LocalMirrorArtifactReader(tmp_path, "hdfs://trusted/artifacts/")
    assert reader.read("hdfs://trusted/artifacts/one", max_bytes=5) == b"hello"
    with pytest.raises(ValueError):
        reader.read("hdfs://trusted/artifacts/one", max_bytes=4)
    for uri in (
        "https://elsewhere/file",
        "hdfs://trusted/artifacts/../secret",
        "hdfs://trusted/artifacts/%2e%2e/secret",
        "hdfs://trusted/artifacts/C:/secret",
    ):
        with pytest.raises(ValueError):
            reader.read(uri, max_bytes=5)


def test_consume_actual_local_collector_store_artifact(tmp_path, mapper):
    content = b'{"dependencies":{"react":"1"}}'
    store = FileArtifactStore(tmp_path)
    batch = batch_with(content)
    row = batch.records[0]
    uri = store.store(
        policy_version=batch.collection_policy.policy_version,
        repo_id=row.github_repo_id,
        pinned_commit_sha=row.pinned_commit_sha,
        path="package.json",
        content=content,
    )
    row = row.model_copy(
        update={"artifacts": (row.artifacts[0].model_copy(update={"uri": uri}),)}
    )
    result = analyze_public_batch(
        batch.model_copy(update={"records": (row,)}),
        LocalMirrorArtifactReader(tmp_path, tmp_path.as_uri()),
        mapper,
    )
    assert result.records[0].status == "READY"
    observation = result.records[0].observations[0]
    assert observation.tech_id == "react"
    assert row.pinned_commit_sha in observation.uri
    assert observation.content_hash == hashlib.sha256(content).hexdigest()
