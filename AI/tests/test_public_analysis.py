import hashlib
import json
from pathlib import Path

import pytest

from common.webhdfs import WebHdfsError
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
    assert result.parser_version == "c-public-static-observations/v4"
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
    assert result.parser_version == "c-public-static-observations/v4"
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
