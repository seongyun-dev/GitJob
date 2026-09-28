"""Config-like text and test variants must not claim production technology use."""

import pytest
from test_analysis_rule_pack_fixtures import _evaluate, _write_repository


@pytest.mark.parametrize(
    "path",
    ["Dockerfile.test", "Dockerfile.spec", "fixtures/Dockerfile", "tests/Dockerfile"],
)
def test_test_only_docker_config_is_not_production_evidence(tmp_path, path):
    _write_repository(tmp_path, {path: "FROM python:3.12\nRUN python -V\n"})
    assert "docker" not in {v.tech_id for v in _evaluate(tmp_path).verdicts}


@pytest.mark.parametrize(
    "source",
    [
        '/*\nprovider "aws" {\n}\n*/\n',
        '// provider "aws" {}\n',
        '# provider "aws" {}\n',
        'locals {\n  example = <<-EOT\nprovider "aws" {\n}\nEOT\n}\n',
    ],
)
def test_commented_or_heredoc_terraform_is_not_cloud_evidence(tmp_path, source):
    _write_repository(tmp_path, {"main.tf": source})
    assert "aws" not in {v.tech_id for v in _evaluate(tmp_path).verdicts}


def test_terraform_real_provider_after_comment_preserves_line_evidence(tmp_path):
    _write_repository(
        tmp_path, {"main.tf": '/* provider "google" {} */\nprovider "aws" {}\n'}
    )
    result = _evaluate(tmp_path)
    assert {v.tech_id for v in result.verdicts} == {"aws"}
    assert all(item.fact.line == 2 for item in result.evidence)
