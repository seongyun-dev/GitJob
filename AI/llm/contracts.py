"""Fact Pack input and summary output contracts for technology summaries.

The backend rules engine decides L0~L3. This boundary only carries the facts
that decision was made from, and the sentence the local model writes about
them. Nothing here judges a level.
"""

import json
from copy import deepcopy
from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

TECHNOLOGY_SUMMARY_REQUEST_SCHEMA_VERSION = "technology-summary-request/v1"

#: A 4B model loses the tail of a long list, and the 8K context has to hold the
#: system prompt and the few-shot pair as well.
MAX_HIGHLIGHTS = 8
MAX_HEADLINE_LENGTH = 40
MAX_SUMMARY_LENGTH = 200

TechId = Annotated[
    str,
    StringConstraints(
        strict=True,
        max_length=80,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]
RegistryVersion = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^registry-[0-9]{8}\.[1-9][0-9]*$",
    ),
]


class EvidenceLevel(StrEnum):
    """Evidence level of a technology, decided by the rules engine."""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class Authorship(StrEnum):
    """Band of the user's own evidence share, never a ratio.

    A count pair such as ``SOLE_AUTHOR 32 / UNVERIFIED 12`` makes the model
    write "about 73%", which the card is not allowed to show. Removing the
    numbers from the input is more reliable than forbidding them in the prompt.
    """

    MOSTLY_MINE = "MOSTLY_MINE"
    MIXED = "MIXED"
    MOSTLY_OTHERS = "MOSTLY_OTHERS"
    NOT_VERIFIED = "NOT_VERIFIED"


class FactType(StrEnum):
    """Kind of fact an evidence row carries.

    Mirrors ``FactTypeV3`` in ``analysis/results.py``, which is what the rules
    engine actually emits. The contract document names only three of these;
    taking it literally would drop every ANNOTATION, SYNTAX_NODE and CONFIG_KEY
    row -- and in the shipped rule pack those are most of the L3 evidence,
    including the ``@EnableMethodSecurity`` the contract's own example asks
    about.
    """

    API_CALL = "API_CALL"
    ANNOTATION = "ANNOTATION"
    SYNTAX_NODE = "SYNTAX_NODE"
    CONFIG_KEY = "CONFIG_KEY"
    IMPORT = "IMPORT"
    SOURCE_FILE = "SOURCE_FILE"
    DEPENDENCY = "DEPENDENCY"


class Confidence(StrEnum):
    """How specific the input was, not how sure the model feels."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class StrictContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def shorten_file_path(file_path: str) -> str:
    """Keep the last two path segments of an evidence file path.

    ``src/main/java/com/example/config/SecurityConfig.java`` costs tokens that
    do not reach the summary; ``config/SecurityConfig.java`` names the file
    just as well.
    """

    segments = [
        segment for segment in file_path.replace("\\", "/").split("/") if segment
    ]
    if not segments:
        raise ValueError("file path must not be blank")
    return "/".join(segments[-2:])


class TechnologyRef(StrictContractModel):
    """The technology this summary is about, with the level already decided."""

    tech_id: TechId
    display_name: StrictStr
    repository_level: EvidenceLevel
    personal_level: EvidenceLevel
    registry_version: RegistryVersion

    @field_validator("display_name")
    @classmethod
    def require_non_blank_display_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("display_name must not be blank")
        return value


class LevelEvidence(StrictContractModel):
    """One reached level and the rules that were satisfied for it."""

    level: EvidenceLevel
    rules: tuple[StrictStr, ...] = Field(min_length=1)
    mine: bool

    @field_validator("rules")
    @classmethod
    def require_non_blank_rules(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not rule.strip() for rule in value):
            raise ValueError("rule must not be blank")
        return value


class NextLevel(StrictContractModel):
    """The level above, and which of its REQUIRED clauses are uncovered.

    "why not L3" tells a person more than "why L2", so this is the field the
    card's actionable sentence comes from.
    """

    level: EvidenceLevel
    rule: StrictStr
    missing: tuple[StrictStr, ...] = Field(min_length=1)

    @field_validator("rule")
    @classmethod
    def require_non_blank_rule(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rule must not be blank")
        return value

    @field_validator("missing")
    @classmethod
    def require_non_blank_missing(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("missing entry must not be blank")
        return value


class Highlight(StrictContractModel):
    """One deduplicated fact, carrying the array position the model echoes.

    The index is sent rather than inferred because a 4B model does not count
    array positions reliably, and ``used_highlights`` is how the backend checks
    the summary against its own input.
    """

    index: int = Field(ge=0, le=MAX_HIGHLIGHTS - 1)
    fact_type: FactType
    value: StrictStr
    file: StrictStr
    mine: bool

    @field_validator("value")
    @classmethod
    def require_non_blank_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value

    @field_validator("file")
    @classmethod
    def shorten_file(cls, value: str) -> str:
        return shorten_file_path(value)


class RepositoryRef(StrictContractModel):
    """A repository the evidence came from."""

    full_name: StrictStr
    mine: bool

    @field_validator("full_name")
    @classmethod
    def require_non_blank_full_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("full_name must not be blank")
        return value


class Period(StrictContractModel):
    """Span of the user's own commits, never the repository's."""

    first: date
    last: date
    months: int = Field(ge=0)

    @model_validator(mode="after")
    def require_ordered_period(self) -> "Period":
        if self.last < self.first:
            raise ValueError("period last must not precede first")
        return self


class FactPack(StrictContractModel):
    """Everything the model is given for one (user, technology) pair.

    Deliberately absent: code snippets, commit SHAs, e-mail addresses, GitHub
    logins, evidence counts, and other contributors' names. None of them reach
    the summary, and counts make the model invent ratios.
    """

    schema_version: Literal["technology-summary-request/v1"]
    locale: StrictStr = "ko-KR"
    technology: TechnologyRef
    authorship: Authorship
    levels: tuple[LevelEvidence, ...] = ()
    next_level: NextLevel | None = None
    highlights: tuple[Highlight, ...] = Field(default=(), max_length=MAX_HIGHLIGHTS)
    repositories: tuple[RepositoryRef, ...] = ()
    period: Period | None = None

    @field_validator("highlights")
    @classmethod
    def require_dense_indexes(
        cls, value: tuple[Highlight, ...]
    ) -> tuple[Highlight, ...]:
        expected = list(range(len(value)))
        if [highlight.index for highlight in value] != expected:
            raise ValueError("highlight indexes must be 0..n-1 in array order")
        return value

    @model_validator(mode="after")
    def reject_self_referencing_next_level(self) -> "FactPack":
        if (
            self.next_level is not None
            and self.next_level.level <= self.technology.personal_level
        ):
            raise ValueError("next_level must be above personal_level")
        return self


class TechnologySummary(StrictContractModel):
    """What the model returns for one Fact Pack.

    Structural validity is not enough: the content checks in
    ``llm.validation`` still run before this is stored or shown.
    """

    tech_id: TechId
    headline: StrictStr = Field(min_length=1, max_length=MAX_HEADLINE_LENGTH)
    summary: StrictStr = Field(min_length=1, max_length=MAX_SUMMARY_LENGTH)
    gap: StrictStr | None = Field(default=None, max_length=MAX_SUMMARY_LENGTH)
    used_highlights: tuple[int, ...] = Field(default=(), max_length=MAX_HIGHLIGHTS)
    confidence: Confidence

    @field_validator("used_highlights")
    @classmethod
    def require_in_range_indexes(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(index < 0 or index >= MAX_HIGHLIGHTS for index in value):
            raise ValueError(f"used_highlights entries must be 0..{MAX_HIGHLIGHTS - 1}")
        return value


#: The schema handed to Ollama as ``format``. It stays inside the subset
#: Ollama's grammar compiler accepts -- no ``$ref``, ``allOf``/``anyOf``/
#: ``oneOf``, ``pattern``, or conditional keywords -- so it cannot be generated
#: from :class:`TechnologySummary`, whose optional ``gap`` would emit ``anyOf``.
#: It constrains syntax only; ``llm.validation`` checks the content.
TECHNOLOGY_SUMMARY_JSON_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://gitjob.local/contracts/technology-summary-v1.schema.json",
    "title": "TechnologySummary",
    "description": "Local LLM -> backend. One object per (user, technology). This "
    "schema is passed to Ollama as `format`, so it must stay inside "
    "the subset Ollama's grammar compiler accepts: no $ref, no "
    "allOf/anyOf/oneOf, no pattern, no conditional keywords. It "
    "constrains syntax only -- a structurally valid object can "
    "still name an API the user never called, so the AI service must "
    "run the content checks in "
    "docs/ai/technology-summary-contract.md ch5 before returning "
    "anything.",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "tech_id",
        "headline",
        "summary",
        "gap",
        "used_highlights",
        "confidence",
    ],
    "properties": {
        "tech_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 80,
            "description": "Echo of the requested "
            "tech_id. The AI service rejects "
            "the response when it differs "
            "-- a 4B model does substitute "
            "a neighbouring technology, "
            "and an unchecked swap would "
            "file Spring Security's "
            "summary under Spring Boot.",
        },
        "headline": {
            "type": "string",
            "minLength": 1,
            "maxLength": 40,
            "description": "One line naming what the "
            "person actually did with the "
            "technology. Shown as the "
            "card title, so it carries no "
            "level string: the level is "
            "rendered beside it and "
            "repeating it wastes the only "
            "line the card has.",
        },
        "summary": {
            "type": "string",
            "minLength": 1,
            "maxLength": 200,
            "description": "Two or three sentences "
            "restating the fact pack in "
            "Korean prose. Restatement, "
            "not inference -- every proper "
            "noun in it must already "
            "appear in highlights.value, "
            "next_level.missing, the "
            "display name, or a repository "
            "name.",
        },
        "gap": {
            "type": ["string", "null"],
            "maxLength": 200,
            "description": "One sentence on what is missing "
            "for the next level, derived from "
            "next_level.missing. Null when "
            "next_level is null (the "
            "technology is already at its "
            "highest defined rule). This "
            "field, not summary, is what makes "
            "the card actionable: 'why not L3' "
            "is more useful to a person than "
            "'why L2'.",
        },
        "used_highlights": {
            "type": "array",
            "maxItems": 8,
            "description": "Indexes of the "
            "highlights the "
            "summary leaned on. "
            "Indexes rather than "
            "evidence ids because "
            "a 4B model reproduces "
            "small integers "
            "reliably and "
            "40-character ids it "
            "does not. The AI service "
            "checks every entry is "
            "in range; an "
            "out-of-range index "
            "means the model "
            "invented a fact and "
            "the whole response is "
            "discarded.",
            "items": {"type": "integer", "minimum": 0, "maximum": 7},
        },
        "confidence": {
            "type": "string",
            "enum": ["HIGH", "MEDIUM", "LOW"],
            "description": "How specific the input "
            "was, not how sure the "
            "model feels. HIGH means "
            "highlights held an "
            "API_CALL the person wrote; "
            "MEDIUM means only imports "
            "or dependencies; LOW means "
            "authorship was "
            "NOT_VERIFIED or highlights "
            "was empty. The screen can "
            "hide LOW summaries without "
            "hiding the level, which "
            "stays rule-derived either "
            "way.",
        },
    },
}


def technology_summary_json_schema() -> dict[str, object]:
    """Return a copy of the Ollama ``format`` schema for the summary output."""

    return deepcopy(TECHNOLOGY_SUMMARY_JSON_SCHEMA)


def canonical_fact_pack_json(fact_pack: FactPack) -> str:
    """Render a Fact Pack the one way the prompt and the cache key both use.

    The cache key is a hash of this string, so it must depend only on the
    contract's field order -- which Pydantic fixes -- and never on how the
    caller happened to build the object.
    """

    return json.dumps(
        fact_pack.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    )
