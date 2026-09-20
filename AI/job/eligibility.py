"""Conservative semantic comparisons for posting eligibility filters."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from enum import StrEnum

__all__ = [
    "CareerState",
    "FilterMatch",
    "RegionState",
    "match_career_level",
    "match_region",
    "normalize_career_level",
    "normalize_region",
]


class FilterMatch(StrEnum):
    """A filter result that keeps uncertainty distinct from a mismatch."""

    MATCHED = "MATCHED"
    UNKNOWN = "UNKNOWN"
    NOT_MATCHED = "NOT_MATCHED"


class RegionState(StrEnum):
    KNOWN = "KNOWN"
    NATIONWIDE = "NATIONWIDE"
    UNKNOWN = "UNKNOWN"


class CareerState(StrEnum):
    KNOWN = "KNOWN"
    UNRESTRICTED = "UNRESTRICTED"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


_REGION_ALIASES = {
    "SEOUL": ("서울특별시", "서울시", "서울"),
    "BUSAN": ("부산광역시", "부산시", "부산"),
    "DAEGU": ("대구광역시", "대구시", "대구"),
    "INCHEON": ("인천광역시", "인천시", "인천"),
    # Bare "광주시" is also a city in Gyeonggi; without the province it is
    # not safe to interpret it as the metropolitan city.
    "GWANGJU": ("광주광역시", "광주"),
    "DAEJEON": ("대전광역시", "대전시", "대전"),
    "ULSAN": ("울산광역시", "울산시", "울산"),
    "SEJONG": ("세종특별자치시", "세종시", "세종"),
    "GYEONGGI": ("경기도", "경기"),
    "GANGWON": ("강원특별자치도", "강원도", "강원"),
    "CHUNGBUK": ("충청북도", "충북"),
    "CHUNGNAM": ("충청남도", "충남"),
    "JEONBUK": ("전북특별자치도", "전라북도", "전북"),
    "JEONNAM": ("전라남도", "전남"),
    "GYEONGBUK": ("경상북도", "경북"),
    "GYEONGNAM": ("경상남도", "경남"),
    "JEJU": ("제주특별자치도", "제주도", "제주"),
}
_ALIASES_BY_LENGTH = tuple(
    sorted(
        (
            (alias, region)
            for region, aliases in _REGION_ALIASES.items()
            for alias in aliases
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)
_REGION_SEPARATOR = re.compile(r"\s*(?:[,;/|·]|\b및\b|\b또는\b)\s*")
_REGION_SUFFIX_BOUNDARY = re.compile(r"^(?:$|[\s>():\-])")
_NATIONWIDE = {"전국", "전국근무", "전국 근무"}


def _text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().split())


def _region_parts(value: str) -> tuple[set[str], bool, bool]:
    regions: set[str] = set()
    unknown = False
    nationwide = False
    for raw_part in _REGION_SEPARATOR.split(_text(value)):
        part = raw_part.strip(" []{}")
        if not part:
            continue
        if part in _NATIONWIDE:
            nationwide = True
            continue
        found = None
        for alias, region in _ALIASES_BY_LENGTH:
            if not part.startswith(alias):
                continue
            suffix = part[len(alias) :]
            if _REGION_SUFFIX_BOUNDARY.match(suffix):
                found = region
                break
        if found is None:
            unknown = True
        else:
            regions.add(found)
    return regions, unknown, nationwide


def normalize_region(value: str | None) -> tuple[tuple[str, ...], RegionState]:
    """Return the same conservative region interpretation used by filtering."""

    if value is None or not value.strip():
        return (), RegionState.UNKNOWN
    regions, unknown, nationwide = _region_parts(value)
    if nationwide:
        return tuple(sorted(regions)), RegionState.NATIONWIDE
    if unknown or not regions:
        return tuple(sorted(regions)), RegionState.UNKNOWN
    return tuple(sorted(regions)), RegionState.KNOWN


def match_region(value: str | None, allowed: Iterable[str]) -> FilterMatch:
    """Compare Korean posting regions at 시/도 level without substring guesses."""

    expected = tuple(item for item in allowed if item and item.strip())
    if not expected:
        return FilterMatch.MATCHED
    if value is None or not value.strip():
        return FilterMatch.UNKNOWN

    normalized_value = _text(value)
    if any(normalized_value.casefold() == _text(item).casefold() for item in expected):
        return FilterMatch.MATCHED

    actual_regions, actual_unknown, nationwide = _region_parts(value)
    if nationwide:
        return FilterMatch.MATCHED

    expected_regions: set[str] = set()
    expected_unknown = False
    for item in expected:
        parsed, unknown, expected_nationwide = _region_parts(item)
        if expected_nationwide:
            return FilterMatch.MATCHED
        expected_regions.update(parsed)
        expected_unknown = expected_unknown or unknown

    if actual_regions & expected_regions:
        return FilterMatch.MATCHED
    if actual_unknown or expected_unknown or not actual_regions or not expected_regions:
        return FilterMatch.UNKNOWN
    return FilterMatch.NOT_MATCHED


_ENTRY = "ENTRY"
_EXPERIENCED = "EXPERIENCED"
_CAREER_UNRESTRICTED = re.compile(r"경력\s*(?:무관|관계\s*없음)")
_ENTRY_EXCLUDED = re.compile(r"신입\s*(?:불가|제외)")
_ENTRY_ONLY = re.compile(r"^신입(?:$|\s*(?:가능|채용|사원|직))")
_EXPERIENCED_ONLY = re.compile(r"^경력(?:$|직|\s*(?:\d+|[일이삼사오육칠팔구십]+)\s*년)")
_LABELLED_EXPERIENCE = re.compile(
    r"^경력\s*\(\s*최소\s*\d+\s*(?:년|개월)\s*이상\)\s*(?:필수)?$"
)


def _career_parts(value: str) -> tuple[set[str], bool]:
    normalized = _text(value)
    if _ENTRY_EXCLUDED.search(normalized):
        return {_EXPERIENCED}, False
    if _CAREER_UNRESTRICTED.search(normalized):
        return {_ENTRY, _EXPERIENCED}, False

    if "신입" in normalized and "경력" in normalized:
        return {_ENTRY, _EXPERIENCED}, False
    if "우대" in normalized:
        return set(), True
    if _ENTRY_ONLY.search(normalized):
        return {_ENTRY}, False
    if _EXPERIENCED_ONLY.search(normalized) or _LABELLED_EXPERIENCE.fullmatch(
        normalized
    ):
        return {_EXPERIENCED}, False
    return set(), True


def normalize_career_level(
    value: str | None,
) -> tuple[tuple[str, ...], CareerState]:
    """Return normalized career codes without inventing meaning for labels."""

    if value is None or not value.strip():
        return (), CareerState.UNKNOWN
    levels, ambiguous = _career_parts(value)
    if ambiguous:
        return tuple(sorted(levels)), CareerState.AMBIGUOUS
    if levels == {_ENTRY, _EXPERIENCED}:
        return tuple(sorted(levels)), CareerState.UNRESTRICTED
    if levels:
        return tuple(sorted(levels)), CareerState.KNOWN
    return (), CareerState.UNKNOWN


def match_career_level(value: str | None, allowed: Iterable[str]) -> FilterMatch:
    """Compare entry/experienced eligibility while preserving unknown labels."""

    expected = tuple(item for item in allowed if item and item.strip())
    if not expected:
        return FilterMatch.MATCHED
    if value is None or not value.strip():
        return FilterMatch.UNKNOWN

    normalized_value = _text(value)
    if any(normalized_value.casefold() == _text(item).casefold() for item in expected):
        return FilterMatch.MATCHED

    actual_levels, actual_unknown = _career_parts(value)
    expected_levels: set[str] = set()
    expected_unknown = False
    for item in expected:
        levels, unknown = _career_parts(item)
        expected_levels.update(levels)
        expected_unknown = expected_unknown or unknown

    if actual_levels & expected_levels:
        return FilterMatch.MATCHED
    if actual_unknown or expected_unknown:
        return FilterMatch.UNKNOWN
    return FilterMatch.NOT_MATCHED
