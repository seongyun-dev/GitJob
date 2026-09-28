from pathlib import Path

import pytest

from registry.contracts import TechnologyRegistry
from trend.github import github_trend, parse_innovation_graph_csv

HEADER = "num_pushers,language,language_type,iso2_code,year,quarter\n"


@pytest.fixture
def registry():
    return TechnologyRegistry.model_validate_json(
        Path("registry/data/technology_registry_v1.json").read_text(encoding="utf-8")
    )


def dataset(rows):
    return parse_innovation_graph_csv(
        HEADER + rows,
        source_version="fixture-v1",
        source_uri="https://github.com/github/innovationgraph/blob/fixture/data/languages.csv",
    )


def test_official_format_kr_quarterly_count_is_not_repo_incidence(registry):
    data = dataset(
        "100,Java,programming,KR,2025,4\n125,Java,programming,KR,2026,1\n999,Java,programming,US,2026,1\n"
    )
    result = github_trend("java", data, registry, periods=("2025-Q4", "2026-Q1"))
    assert result.status == "READY"
    assert result.metric == "num_pushers"
    assert result.unit == "UNIQUE_PUSHERS"
    assert [p.value for p in result.points] == [100, 125]
    assert result.points[1].absolute_change == 25
    assert result.points[1].relative_change == 0.25
    assert result.points[1].denominator is None
    assert result.points[1].source_version == "fixture-v1"


def test_missing_prior_and_current_not_fabricated_zero(registry):
    result = github_trend(
        "java",
        dataset("125,Java,programming,KR,2026,1\n"),
        registry,
        periods=("2025-Q4", "2026-Q1", "2026-Q2"),
    )
    assert result.status == "INSUFFICIENT_DATA"
    assert [p.value for p in result.points] == [None, 125, None]
    assert result.points[1].relative_change is None


def test_previous_zero_absolute_only(registry):
    result = github_trend(
        "java",
        dataset("0,Java,programming,KR,2025,4\n5,Java,programming,KR,2026,1\n"),
        registry,
        periods=("2025-Q4", "2026-Q1"),
    )
    assert result.points[1].absolute_change == 5
    assert result.points[1].relative_change is None
    assert "PREVIOUS_ZERO" in result.points[1].reasons


def test_library_unsupported_even_when_java_present(registry):
    result = github_trend(
        "apache-kafka",
        dataset("100,Java,programming,KR,2026,1\n"),
        registry,
        periods=("2026-Q1",),
    )
    assert result.status == "NOT_SUPPORTED"
    assert not result.points


def test_not_arrived_preparing(registry):
    assert (
        github_trend("java", None, registry, periods=("2026-Q1",)).status == "PREPARING"
    )


def test_new_python_registry_source_mapping_is_consumable():
    registry = TechnologyRegistry.model_validate_json(
        Path("registry/data/technology_registry_20260908_1.json").read_text(
            encoding="utf-8"
        )
    )
    result = github_trend(
        "python",
        dataset("100,Python,programming,KR,2025,4\n120,Python,programming,KR,2026,1\n"),
        registry,
        periods=("2025-Q4", "2026-Q1"),
    )
    assert result.status == "READY"
    assert result.points[1].absolute_change == 20
    assert (
        github_trend("django", None, registry, periods=("2026-Q1",)).status
        == "NOT_SUPPORTED"
    )


@pytest.mark.parametrize(
    "row",
    [
        "-1,Python,programming,KR,2026,1",
        "1.1,Python,programming,KR,2026,1",
        "nan,Python,programming,KR,2026,1",
        "1,Python,programming,KR,2026,5",
        "1,Python,programming,KR,2019,1",
    ],
)
def test_reject_invalid_official_values(row):
    with pytest.raises(ValueError):
        dataset(row + "\n")


def test_duplicate_source_row_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        dataset("1,Python,programming,KR,2026,1\n1,Python,programming,KR,2026,1\n")


@pytest.mark.parametrize(
    "periods", [("2026-Q5",), ("2026-Q1", "2026-Q1"), ("2026-Q2", "2026-Q1")]
)
def test_bad_request_periods(registry, periods):
    with pytest.raises(ValueError):
        github_trend("python", None, registry, periods=periods)
