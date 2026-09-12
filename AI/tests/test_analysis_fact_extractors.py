from __future__ import annotations

import pytest

from analysis.configs import ConfigScanner, facts_from_configs
from analysis.judge import facts_from_annotations, facts_from_sources
from analysis.manifests import (
    MANIFEST_PARSER_VERSION,
    ManifestScanner,
    parse_manifest_bytes,
    supports_manifest_path,
)
from analysis.parse import RepositoryParser


def test_source_and_annotation_facts_come_from_repository_files(tmp_path):
    source = tmp_path / "src" / "Service.java"
    source.parent.mkdir()
    source.write_text(
        "package demo;\n@Service\nclass Service {\n  void run() {}\n}\n",
        encoding="utf-8",
    )
    vendor = tmp_path / "vendor" / "Ignored.java"
    vendor.parent.mkdir()
    vendor.write_text("@Entity class Ignored {}\n", encoding="utf-8")

    report = RepositoryParser().parse_repository(tmp_path)
    source_facts = facts_from_sources(report.sources)
    annotation_facts = facts_from_annotations(report.annotations)

    assert [
        (fact.fact_type, fact.fields["LANGUAGE"], fact.file) for fact in source_facts
    ] == [("SOURCE_FILE", "java", "src/Service.java")]
    assert source_facts[0].fields["SLOC"] == "5"
    assert source_facts[0].fields["IS_TEST"] == "false"
    assert [
        (fact.fields["NAME"], fact.file, fact.line) for fact in annotation_facts
    ] == [("Service", "src/Service.java", 2)]


def test_test_source_is_marked_and_generated_suffix_is_excluded(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "sample.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    (tests / "types.d.ts").write_text("declare const x: string;\n", encoding="utf-8")

    report = RepositoryParser().parse_repository(tmp_path)

    assert [(item.file, item.is_test) for item in report.sources] == [
        ("tests/sample.py", True)
    ]


def test_config_facts_preserve_path_key_value_and_line(tmp_path):
    (tmp_path / "Dockerfile").write_text(
        "FROM python:3.12 AS build\nRUN pip install .\nUSER 1000\nHEALTHCHECK CMD true\n",
        encoding="utf-8",
    )
    (tmp_path / "compose.yaml").write_text(
        "services:\n  db:\n    image: postgres:16\n    healthcheck:\n      test: [CMD, true]\n",
        encoding="utf-8",
    )

    report = ConfigScanner().scan(tmp_path)
    facts = facts_from_configs(report.occurrences)

    assert any(
        fact.fields["FORMAT"] == "DOCKERFILE"
        and fact.fields["KEY"] == "FROM"
        and fact.fields["VALUE"] == "python:3.12 AS build"
        and fact.line == 1
        for fact in facts
    )
    assert any(
        fact.fields["FORMAT"] == "COMPOSE"
        and fact.fields["KEY"] == "services.db.image"
        and fact.fields["VALUE"] == "postgres:16"
        for fact in facts
    )


def test_manifest_bytes_api_is_the_scanner_parser_without_a_temp_tree(tmp_path):
    content = (
        b"module example.com/demo\n\nrequire github.com/redis/go-redis/v9 v9.0.0\n"
    )

    parsed = parse_manifest_bytes("go.mod", content)
    (tmp_path / "go.mod").write_bytes(content)
    scanned = ManifestScanner().scan(tmp_path).occurrences

    assert parsed == scanned
    assert parsed[0].ecosystem == "GO"
    assert parsed[0].coordinate == "github.com/redis/go-redis/v9"
    assert parsed[0].line == 3


def test_manifest_bytes_supports_composer_and_cargo():
    composer = parse_manifest_bytes(
        "composer.json", b'{"require":{"php":"^8.2","laravel/framework":"^11"}}'
    )
    cargo = parse_manifest_bytes(
        "Cargo.toml",
        b'[dependencies]\nserde = "1"\n[dev-dependencies]\nmockall = "0.13"\n',
    )

    assert [(item.ecosystem, item.coordinate, item.scope) for item in composer] == [
        ("COMPOSER", "laravel/framework", "require")
    ]
    assert [(item.ecosystem, item.coordinate, item.scope) for item in cargo] == [
        ("CARGO", "serde", "dependencies"),
        ("CARGO", "mockall", "dev-dependencies"),
    ]


def test_manifest_bytes_exposes_stable_support_identity_and_empty_distinction():
    assert MANIFEST_PARSER_VERSION == "repository-manifest-parser/v2"
    assert supports_manifest_path("requirements-dev.txt")
    assert (
        parse_manifest_bytes("requirements-dev.txt", b"# intentionally empty\n") == ()
    )
    assert not supports_manifest_path("README.md")
    assert parse_manifest_bytes("README.md", b"Django==5.1\n") == ()


def test_nonempty_bare_requirements_path_fails_closed():
    with pytest.raises(ValueError, match="no parseable dependency"):
        parse_manifest_bytes(
            "docs/requirements.txt",
            b"../build/requirements-docs.txt\n",
        )


def test_comments_and_strings_do_not_emit_source_or_annotation_evidence(tmp_path):
    (tmp_path / "OnlyComment.py").write_text(
        "# @decorator\n# import torch\n", encoding="utf-8"
    )
    (tmp_path / "Text.java").write_text(
        'class Text { String value = "@Service"; } // @Entity\n',
        encoding="utf-8",
    )

    report = RepositoryParser().parse_repository(tmp_path)

    assert all(item.file != "OnlyComment.py" for item in report.sources)
    assert report.annotations == ()
