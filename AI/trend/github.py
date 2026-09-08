"""Adapter for the official Innovation Graph languages.csv schema."""

import csv
import hashlib
import io
import re
from dataclasses import dataclass

from registry.contracts import MappingType, RegistryStatus, TechnologyRegistry
from registry.mapper import MapperInput, MapperSource, MatchStatus, RegistryMapper
from trend.contracts import (
    TrendPoint,
    TrendResult,
    TrendStatus,
    compare_points,
    validate_periods,
)

OFFICIAL_COLUMNS = {
    "num_pushers",
    "language",
    "language_type",
    "iso2_code",
    "year",
    "quarter",
}


@dataclass(frozen=True)
class LanguageObservation:
    language: str
    language_type: str
    country: str
    period: str
    num_pushers: int


@dataclass(frozen=True)
class InnovationGraphDataset:
    observations: tuple[LanguageObservation, ...]
    source_version: str
    source_uri: str
    source_hash: str


def parse_innovation_graph_csv(
    text: str, *, source_version: str, source_uri: str
) -> InnovationGraphDataset:
    """Parse received official CSV; no network access or implicit version selection."""
    if not source_version.strip() or not source_uri.strip():
        raise ValueError("source_version and source_uri are required")
    reader = csv.DictReader(io.StringIO(text.removeprefix("\ufeff")))
    if (
        reader.fieldnames is None
        or set(reader.fieldnames) != OFFICIAL_COLUMNS
        or len(reader.fieldnames) != len(OFFICIAL_COLUMNS)
    ):
        raise ValueError("invalid Innovation Graph languages.csv header")
    observations = []
    keys = set()
    for row in reader:
        if set(row) != OFFICIAL_COLUMNS or any(value is None for value in row.values()):
            raise ValueError("invalid Innovation Graph row width")
        if any(
            not re.fullmatch(r"[0-9]+", row[name])
            for name in ("num_pushers", "year", "quarter")
        ):
            raise ValueError("invalid nonnegative integer in Innovation Graph row")
        year, quarter, count = (
            int(row[name]) for name in ("year", "quarter", "num_pushers")
        )
        if year < 2020 or year > 9999 or quarter not in range(1, 5):
            raise ValueError("invalid Innovation Graph period")
        if not row["language"].strip() or row["language_type"] not in {
            "programming",
            "markup",
            "data",
            "prose",
        }:
            raise ValueError("invalid language or language_type")
        # The official dataset includes WORLD in addition to economy codes.
        if not re.fullmatch(r"[A-Z]{2}|WORLD", row["iso2_code"]):
            raise ValueError("invalid economy code")
        key = (row["iso2_code"], row["language"], year, quarter)
        if key in keys:
            raise ValueError("duplicate Innovation Graph language/economy/period")
        keys.add(key)
        observations.append(
            LanguageObservation(
                row["language"],
                row["language_type"],
                row["iso2_code"],
                f"{year}-Q{quarter}",
                count,
            )
        )
    return InnovationGraphDataset(
        tuple(observations),
        source_version,
        source_uri,
        hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def github_trend(
    tech_id: str,
    dataset: InnovationGraphDataset | None,
    registry: TechnologyRegistry,
    *,
    periods: tuple[str, ...],
) -> TrendResult:
    indices = validate_periods(periods, quarterly=True)
    common = {
        "source": "GITHUB",
        "tech_id": tech_id,
        "metric": "num_pushers",
        "unit": "UNIQUE_PUSHERS",
        "granularity": "QUARTER",
        "registry_version": registry.registry_version,
        "filters": {"country": "KR"},
    }
    mapper = RegistryMapper(registry)
    languages = set()
    for mapping in registry.mappings:
        if (
            mapping.tech_id != tech_id
            or mapping.mapping_type is not MappingType.GITHUB_LANGUAGE
            or mapping.status is not RegistryStatus.ACTIVE
        ):
            continue
        result = mapper.map(
            MapperInput(source=MapperSource.GITHUB_LANGUAGE, raw_value=mapping.value)
        )
        if result.status is MatchStatus.MATCHED and result.tech_id == tech_id:
            languages.add(mapping.value.casefold())
    if len(languages) != 1:
        return TrendResult(
            **common,
            status=TrendStatus.NOT_SUPPORTED,
            reasons=("NO_UNIQUE_GITHUB_LANGUAGE_MAPPING",),
        )
    if dataset is None:
        return TrendResult(
            **common, status=TrendStatus.PREPARING, reasons=("INPUT_NOT_AVAILABLE",)
        )
    values = {}
    for row in dataset.observations:
        if (
            row.country != "KR"
            or row.language.casefold() not in languages
            or row.period not in periods
        ):
            continue
        if row.period in values:
            return TrendResult(
                **common,
                status=TrendStatus.FAILED,
                reasons=("DUPLICATE_MAPPED_PERIOD",),
                source_hash=dataset.source_hash,
            )
        values[row.period] = row.num_pushers
    points = tuple(
        TrendPoint(
            period=period,
            value=values.get(period),
            source_version=dataset.source_version,
            source_uri=dataset.source_uri,
            reasons=() if period in values else ("SOURCE_ROW_MISSING",),
        )
        for period in periods
    )
    points = compare_points(points, indices)
    complete = (
        all(p.value is not None for p in points)
        and len(points) >= 2
        and all(indices[i] == indices[i - 1] + 1 for i in range(1, len(indices)))
    )
    return TrendResult(
        **common,
        status=TrendStatus.READY if complete else TrendStatus.INSUFFICIENT_DATA,
        reasons=() if complete else ("MISSING_PERIOD_OR_BASELINE",),
        points=points,
        source_hash=dataset.source_hash,
    )
