"""Conservative, source-grounded job requirement clause extraction."""

import re
from collections import defaultdict
from enum import StrEnum
from itertools import pairwise
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from job.classifier import (
    JOB_REQUIREMENT_PARSER_VERSION,
    JobClassificationRecord,
    RequirementClass,
    TechnologyClassification,
)
from job.contracts import (
    ContentHash,
    JobPostingInput,
    RequirementType,
    SourceSurface,
)
from registry.contracts import TechId
from registry.mapper import MatchStatus

JOB_REQUIREMENTS_SCHEMA_VERSION = "job-requirements/v1"


class RequirementKind(StrEnum):
    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"


class RequirementOperator(StrEnum):
    """A clause is satisfied by any one positive technology operand.

    Conjunction is represented as multiple independent clauses instead of a
    second operator nested inside a clause.
    """

    ANY_OF = "ANY_OF"


class UnresolvedReason(StrEnum):
    TECHNOLOGY_MAPPING_UNRESOLVED = "TECHNOLOGY_MAPPING_UNRESOLVED"
    EVIDENCE_NOT_LOCATED = "EVIDENCE_NOT_LOCATED"
    NEGATION_UNSUPPORTED = "NEGATION_UNSUPPORTED"
    CARDINALITY_UNSUPPORTED = "CARDINALITY_UNSUPPORTED"
    LOGIC_UNSUPPORTED = "LOGIC_UNSUPPORTED"


class RequirementModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RequirementEvidence(RequirementModel):
    source_surface: SourceSurface
    char_start: StrictInt | None
    char_end: StrictInt | None
    text: StrictStr
    mention_indices: tuple[StrictInt, ...] = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def require_non_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence text must not be blank")
        return value

    @field_validator("mention_indices")
    @classmethod
    def canonicalize_mention_indices(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(value < 0 for value in values):
            raise ValueError("mention indices must be non-negative")
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def validate_location_pair(self) -> "RequirementEvidence":
        if (self.char_start is None) != (self.char_end is None):
            raise ValueError("evidence offsets must both be present or both be absent")
        if self.char_start is not None and (
            self.char_start < 0 or self.char_end <= self.char_start
        ):
            raise ValueError("evidence offsets must describe a non-empty range")
        return self


class RequirementClause(RequirementModel):
    operator: RequirementOperator = RequirementOperator.ANY_OF
    tech_ids: tuple[TechId, ...] = Field(min_length=1)
    evidence_refs: tuple[RequirementEvidence, ...] = Field(min_length=1)

    @field_validator("tech_ids")
    @classmethod
    def canonicalize_tech_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class UnresolvedRequirement(RequirementModel):
    requirement_kind: RequirementKind
    reason: UnresolvedReason
    known_tech_ids: tuple[TechId, ...] = ()
    raw_operands: tuple[StrictStr, ...] = ()
    evidence: RequirementEvidence

    @field_validator("known_tech_ids")
    @classmethod
    def canonicalize_known_tech_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @field_validator("raw_operands")
    @classmethod
    def canonicalize_raw_operands(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values if value.strip())
        return tuple(dict.fromkeys(normalized))


class JobRequirements(RequirementModel):
    schema_version: Literal["job-requirements/v1"] = JOB_REQUIREMENTS_SCHEMA_VERSION
    source_record_id: StrictStr
    content_hash: ContentHash
    parser_version: StrictStr
    required: tuple[RequirementClause, ...] = ()
    preferred: tuple[RequirementClause, ...] = ()
    unresolved: tuple[UnresolvedRequirement, ...] = ()

    @property
    def required_count(self) -> int:
        return len(self.required)

    @property
    def preferred_count(self) -> int:
        return len(self.preferred)

    def unresolved_for(
        self, requirement_kind: RequirementKind
    ) -> tuple[UnresolvedRequirement, ...]:
        return tuple(
            item
            for item in self.unresolved
            if item.requirement_kind is requirement_kind
        )


_OR = re.compile(r"\bor\b|또는|혹은|아니면", re.IGNORECASE)
_AND = re.compile(r"\band\b|및|그리고|&|\+", re.IGNORECASE)
_ACTIVITY_CONJUNCTION = re.compile(
    r"(?<!\w)(?:개발\s+및\s+운영|구축\s+및\s+운용|설계\s+및\s+구현)(?!\w)"
)
_NEGATION = re.compile(
    r"없어도|무관|불필요|경험(?:이)?\s*없는|"
    r"필수(?:\s*(?:가|는|은))?\s*아(?:니|닌|닙|님|닐)\w*|"
    r"\boptional\b|\bnot\s+(?:required|necessary|needed|(?:a\s+)?requirement)\b",
    re.IGNORECASE,
)
_CARDINALITY = re.compile(
    r"(?:(?<!\d)(?:[2-9]|[1-9]\d+)\s*(?:개|가지)|"
    r"(?:두|둘|세|셋|네|넷)\s*(?:개|가지))\s*이상"
)
_UNCERTAIN_EXAMPLE = re.compile(
    r"예시|예를|\betc\b|등(?=\s|[,.]|$|[을의])", re.IGNORECASE
)
_ONE_OF = re.compile(r"중\s*(?:하나|1개)|\b(?:one|any)\s+of\b", re.IGNORECASE)
_ONE_OF_PRELUDE = re.compile(
    r"(?:[-*•]\s*)?(?:(?:one|any)\s+of\s+(?:the\s+)?following|"
    r"(?:다음|아래)\s*(?:기술|항목)?\s*중\s*(?:하나|1개))\s*[:：]?",
    re.IGNORECASE,
)
_SENTENCE_BOUNDARY = re.compile(r"(?:[;；。]|\.(?=\s))\s*")

_REQUIRED_HEADINGS = frozenset(
    {
        "자격요건",
        "지원자격",
        "필수",
        "필수사항",
        "필수역량",
        "요구사항",
        "requirements",
        "required",
        "담당업무",
        "주요업무",
        "업무내용",
        "직무내용",
        "responsibilities",
    }
)
_PREFERRED_HEADINGS = frozenset(
    {"우대", "우대사항", "우대조건", "우대자격요건", "preferred", "nicetohave"}
)
_GENERAL_HEADINGS = frozenset(
    {
        "기술스택",
        "사용기술",
        "복리후생",
        "근무조건",
        "채용절차",
        "benefits",
        "회사소개",
        "기업소개",
        "company",
        "aboutus",
    }
)


def _heading_key(value: str | None) -> str:
    if value is None:
        return ""
    label = value.casefold().strip().strip("[]()#*•-:：")
    label = re.sub(r"^(?:(?:[0-9]{1,2}[.)]|[📋🏠🎁🚀])\s*)+", "", label)
    return "".join(label.split()).strip("[]()#*•-:：")


def _requirement_kind(item: TechnologyClassification) -> RequirementKind | None:
    if item.requirement_class is RequirementClass.REQUIRED:
        return RequirementKind.REQUIRED
    if item.requirement_class is RequirementClass.PREFERRED:
        return RequirementKind.PREFERRED
    if item.requirement_class is RequirementClass.SKILL:
        return None

    for section in (item.parsed_section, item.evidence_section):
        heading = _heading_key(section)
        if heading in _GENERAL_HEADINGS:
            return None
        if heading in _REQUIRED_HEADINGS:
            return RequirementKind.REQUIRED
        if heading in _PREFERRED_HEADINGS:
            return RequirementKind.PREFERRED
    if item.input_requirement_type is RequirementType.REQUIRED:
        return RequirementKind.REQUIRED
    if item.input_requirement_type is RequirementType.PREFERRED:
        return RequirementKind.PREFERRED
    return None


def _surface(record: JobPostingInput, source: SourceSurface) -> str | None:
    return record.title if source is SourceSurface.TITLE else record.description_text


def _section_kind(label: str) -> RequirementKind | Literal["GENERAL"] | None:
    heading = _heading_key(label)
    if heading in _REQUIRED_HEADINGS:
        return RequirementKind.REQUIRED
    if heading in _PREFERRED_HEADINGS:
        return RequirementKind.PREFERRED
    if heading in _GENERAL_HEADINGS:
        return "GENERAL"
    return None


def _segment_bounds(surface: str, start: int, end: int) -> tuple[int, int]:
    line_start = surface.rfind("\n", 0, start) + 1
    line_end = surface.find("\n", end)
    line_end = len(surface) if line_end < 0 else line_end
    for boundary in _SENTENCE_BOUNDARY.finditer(surface, line_start, line_end):
        if boundary.end() <= start:
            line_start = boundary.end()
        elif boundary.start() >= end:
            line_end = boundary.start()
            break
    while line_start < line_end and surface[line_start].isspace():
        line_start += 1
    while line_end > line_start and surface[line_end - 1].isspace():
        line_end -= 1
    return line_start, line_end


def _evidence_sort_key(evidence: RequirementEvidence) -> tuple[object, ...]:
    surface_order = 0 if evidence.source_surface is SourceSurface.TITLE else 1
    return (
        surface_order,
        evidence.char_start is None,
        evidence.char_start if evidence.char_start is not None else 0,
        evidence.char_end if evidence.char_end is not None else 0,
        evidence.text,
        evidence.mention_indices,
    )


def _merge_evidence(
    evidences: tuple[RequirementEvidence, ...],
) -> tuple[RequirementEvidence, ...]:
    merged: dict[tuple[object, ...], set[int]] = defaultdict(set)
    for evidence in evidences:
        key = (
            evidence.source_surface,
            evidence.char_start,
            evidence.char_end,
            evidence.text,
        )
        merged[key].update(evidence.mention_indices)
    return tuple(
        sorted(
            (
                RequirementEvidence(
                    source_surface=key[0],
                    char_start=key[1],
                    char_end=key[2],
                    text=key[3],
                    mention_indices=tuple(indices),
                )
                for key, indices in merged.items()
            ),
            key=_evidence_sort_key,
        )
    )


def _technology_spans(
    text: str, items: list[TechnologyClassification]
) -> list[tuple[int, int, str, str | None]]:
    spans = set()
    for item in items:
        pattern = rf"(?<![A-Za-z0-9]){re.escape(item.raw_technology)}(?![A-Za-z0-9])"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            spans.add((match.start(), match.end(), item.raw_technology, item.tech_id))
    return sorted(spans, key=lambda value: (value[0], value[1], value[2].casefold()))


def _mask_spans(text: str, spans: list[tuple[int, int, str, str | None]]) -> str:
    masked = text
    for start, end, _, _ in reversed(spans):
        masked = masked[:start] + " " * (end - start) + masked[end:]
    for activity in _ACTIVITY_CONJUNCTION.finditer(text):
        start, end = activity.span()
        masked = masked[:start] + " " * (end - start) + masked[end:]
    return masked


def _missing_operand_fragments(
    text: str, spans: list[tuple[int, int, str, str | None]]
) -> tuple[str, ...]:
    masked = _mask_spans(text, spans)
    boundaries = (
        ((0, spans[0][0]),)
        + tuple((left[1], right[0]) for left, right in pairwise(spans))
        + ((spans[-1][1], len(text)),)
    )
    operands = []
    for start, end in boundaries:
        masked_fragment = masked[start:end]
        if not (_OR.search(masked_fragment) or _AND.search(masked_fragment)):
            continue
        fragment = text[start:end]
        fragment = re.sub(
            r"\bor\b|\band\b|또는|혹은|아니면|및|그리고|&|\+",
            " ",
            fragment,
            flags=re.IGNORECASE,
        )
        value = fragment.strip(" \t,./:：()[]{}-*•")
        value = re.sub(
            r"\s+(?:(?:개발|사용|운영|실무|관련)\s*)?(?:경험|역량|지식|능력).*$",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()
        value = re.sub(
            r"^(?:experience|knowledge|proficiency)\s+(?:with|in)\s+",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()
        if value and re.search(r"[A-Za-z가-힣]", value):
            operands.append(value)
    return tuple(dict.fromkeys(operands))


def _unresolved_reason(
    text: str, items: list[TechnologyClassification]
) -> UnresolvedReason | None:
    if _NEGATION.search(text):
        return UnresolvedReason.NEGATION_UNSUPPORTED
    if _CARDINALITY.search(text):
        return UnresolvedReason.CARDINALITY_UNSUPPORTED
    if _UNCERTAIN_EXAMPLE.search(text):
        return UnresolvedReason.LOGIC_UNSUPPORTED
    if any(item.match_status is not MatchStatus.MATCHED for item in items):
        return UnresolvedReason.TECHNOLOGY_MAPPING_UNRESOLVED
    if any(
        item.requirement_class is RequirementClass.REVIEW_REQUIRED for item in items
    ):
        return UnresolvedReason.LOGIC_UNSUPPORTED
    return None


def _parse_segment(
    kind: RequirementKind,
    text: str,
    evidence: RequirementEvidence,
    items: list[TechnologyClassification],
) -> tuple[
    list[tuple[tuple[str, ...], RequirementEvidence]], UnresolvedRequirement | None
]:
    known_ids = tuple(
        sorted(
            {
                item.tech_id
                for item in items
                if item.match_status is MatchStatus.MATCHED and item.tech_id is not None
            }
        )
    )
    unknown_operands = tuple(
        dict.fromkeys(
            item.raw_technology
            for item in items
            if item.match_status is not MatchStatus.MATCHED or item.tech_id is None
        )
    )
    spans = _technology_spans(text, items)
    reason = _unresolved_reason(text, items)
    if reason is not None:
        return [], UnresolvedRequirement(
            requirement_kind=kind,
            reason=reason,
            known_tech_ids=known_ids,
            raw_operands=unknown_operands,
            evidence=evidence,
        )
    if not spans or any(left[1] > right[0] for left, right in pairwise(spans)):
        return [], UnresolvedRequirement(
            requirement_kind=kind,
            reason=UnresolvedReason.LOGIC_UNSUPPORTED,
            known_tech_ids=known_ids,
            raw_operands=unknown_operands,
            evidence=evidence,
        )

    masked = _mask_spans(text, spans)
    has_or = bool(_OR.search(masked) or _ONE_OF.search(masked))
    has_and = bool(_AND.search(masked))
    missing_fragments = _missing_operand_fragments(text, spans)
    if "/" in masked or (has_or and has_and):
        return [], UnresolvedRequirement(
            requirement_kind=kind,
            reason=UnresolvedReason.LOGIC_UNSUPPORTED,
            known_tech_ids=known_ids,
            raw_operands=unknown_operands or missing_fragments,
            evidence=evidence,
        )

    prefix, suffix = masked[: spans[0][0]], masked[spans[-1][1] :]
    if (
        _OR.search(prefix)
        or _OR.search(suffix)
        or _AND.search(prefix)
        or _AND.search(suffix)
    ):
        return [], UnresolvedRequirement(
            requirement_kind=kind,
            reason=(
                UnresolvedReason.TECHNOLOGY_MAPPING_UNRESOLVED
                if has_or and missing_fragments
                else UnresolvedReason.LOGIC_UNSUPPORTED
            ),
            known_tech_ids=known_ids,
            raw_operands=unknown_operands or missing_fragments,
            evidence=evidence,
        )

    if has_or:
        if len(spans) < 2:
            return [], UnresolvedRequirement(
                requirement_kind=kind,
                reason=UnresolvedReason.LOGIC_UNSUPPORTED,
                known_tech_ids=known_ids,
                raw_operands=unknown_operands or missing_fragments,
                evidence=evidence,
            )
        for left, right in pairwise(spans):
            connector = masked[left[1] : right[0]].strip()
            allowed = (
                r"(?:또는|혹은|아니면|or)"
                if not _ONE_OF.search(masked)
                else r"(?:또는|혹은|아니면|or|,)"
            )
            if re.fullmatch(allowed, connector, re.IGNORECASE) is None:
                return [], UnresolvedRequirement(
                    requirement_kind=kind,
                    reason=UnresolvedReason.LOGIC_UNSUPPORTED,
                    known_tech_ids=known_ids,
                    raw_operands=unknown_operands or missing_fragments,
                    evidence=evidence,
                )
        return [(known_ids, evidence)], None

    if has_and and any(
        re.fullmatch(
            r"\s*(?:and|및|그리고|&|\+|,|\s)+",
            masked[left[1] : right[0]],
            re.IGNORECASE,
        )
        is None
        for left, right in pairwise(spans)
    ):
        return [], UnresolvedRequirement(
            requirement_kind=kind,
            reason=UnresolvedReason.LOGIC_UNSUPPORTED,
            known_tech_ids=known_ids,
            raw_operands=unknown_operands or missing_fragments,
            evidence=evidence,
        )
    if re.search(r",\s*$", prefix) or re.match(r"\s*,", suffix):
        return [], UnresolvedRequirement(
            requirement_kind=kind,
            reason=UnresolvedReason.LOGIC_UNSUPPORTED,
            known_tech_ids=known_ids,
            raw_operands=unknown_operands or missing_fragments,
            evidence=evidence,
        )
    return [((tech_id,), evidence) for tech_id in known_ids], None


def extract_job_requirements(
    record: JobPostingInput,
    classification: JobClassificationRecord,
) -> JobRequirements:
    """Preserve independently resolvable clauses and every unresolved source span.

    The extractor intentionally accepts only the current classifier output for
    the same immutable source record. It performs no Registry mapping itself and
    does not change the strict cohort inclusion calculation.
    """

    if (
        record.source_record_id != classification.source_record_id
        or record.content_hash != classification.content_hash
        or len(record.technology_mentions) != len(classification.technologies)
    ):
        raise ValueError("record and classification must describe the same source")
    if any(
        item.mention_index != index
        or item.raw_technology != record.technology_mentions[index].raw_technology
        for index, item in enumerate(classification.technologies)
    ):
        raise ValueError("classification mention lineage does not match the record")

    located_duplicates: dict[
        tuple[RequirementKind, SourceSurface, str, str], tuple[int, int]
    ] = {}
    for item in classification.technologies:
        kind = _requirement_kind(item)
        if (
            kind is not None
            and item.location.char_start is not None
            and item.location.char_end is not None
        ):
            located_duplicates.setdefault(
                (
                    kind,
                    item.location.source_surface,
                    item.evidence_text,
                    item.raw_technology.casefold(),
                ),
                (item.location.char_start, item.location.char_end),
            )

    groups: defaultdict[
        tuple[RequirementKind, SourceSurface, int, int, str],
        list[TechnologyClassification],
    ] = defaultdict(list)
    unlocated: defaultdict[
        tuple[RequirementKind, SourceSurface, str], list[TechnologyClassification]
    ] = defaultdict(list)
    for item in classification.technologies:
        kind = _requirement_kind(item)
        if kind is None:
            continue
        surface = _surface(record, item.location.source_surface)
        start, end = item.location.char_start, item.location.char_end
        if start is None or end is None:
            duplicate_location = located_duplicates.get(
                (
                    kind,
                    item.location.source_surface,
                    item.evidence_text,
                    item.raw_technology.casefold(),
                )
            )
            if duplicate_location is not None:
                start, end = duplicate_location
        if (
            surface is None
            or start is None
            or end is None
            or start < 0
            or end > len(surface)
            or start >= end
        ):
            unlocated[(kind, item.location.source_surface, item.evidence_text)].append(
                item
            )
            continue
        raw_pattern = (
            rf"(?<![A-Za-z0-9]){re.escape(item.raw_technology)}(?![A-Za-z0-9])"
        )
        occurrences = tuple(re.finditer(raw_pattern, surface[start:end], re.IGNORECASE))
        occurrence_ranges = {
            _segment_bounds(
                surface,
                start + occurrence.start(),
                start + occurrence.end(),
            )
            for occurrence in occurrences
        }
        if not occurrence_ranges:
            occurrence_ranges = {_segment_bounds(surface, start, end)}
        for segment_start, segment_end in occurrence_ranges:
            segment_text = surface[segment_start:segment_end]
            groups[
                (
                    kind,
                    item.location.source_surface,
                    segment_start,
                    segment_end,
                    segment_text,
                )
            ].append(item)

    # Some collectors intentionally emit one mention per technology even when
    # the same technology occurs in multiple source statements. Revisit only
    # explicit requirement sections and only for already classified technology
    # surface forms. This recovers repeated evidence and lets an expression such
    # as ``Java or unmapped-token`` remain unresolved without attempting a new
    # Registry mapping or treating arbitrary prose as a requirement.
    if record.description_text is not None:
        by_raw: defaultdict[str, list[TechnologyClassification]] = defaultdict(list)
        for item in classification.technologies:
            if (
                item.location.source_surface is SourceSurface.BODY
                and item.location.char_start is not None
                and item.location.char_end is not None
            ):
                by_raw[item.raw_technology.casefold()].append(item)
        active_section: RequirementKind | Literal["GENERAL"] | None = None
        offset = 0
        for line_with_end in record.description_text.splitlines(keepends=True):
            line = line_with_end.rstrip("\r\n")
            heading = re.split(r"[:：]", line.strip(), maxsplit=1)[0].strip()
            section = _section_kind(heading)
            if section is not None:
                active_section = section
                offset += len(line_with_end)
                continue
            if active_section not in (
                RequirementKind.REQUIRED,
                RequirementKind.PREFERRED,
            ):
                offset += len(line_with_end)
                continue
            for candidates in by_raw.values():
                raw = candidates[0].raw_technology
                pattern = rf"(?<![A-Za-z0-9]){re.escape(raw)}(?![A-Za-z0-9])"
                occurrences = tuple(re.finditer(pattern, line, re.IGNORECASE))
                if not occurrences:
                    continue
                candidate = next(
                    (
                        item
                        for item in candidates
                        if _requirement_kind(item) is active_section
                    ),
                    candidates[0],
                )
                for occurrence in occurrences:
                    start, end = _segment_bounds(
                        record.description_text,
                        offset + occurrence.start(),
                        offset + occurrence.end(),
                    )
                    groups[
                        (
                            active_section,
                            SourceSurface.BODY,
                            start,
                            end,
                            record.description_text[start:end],
                        )
                    ].append(candidate)
            offset += len(line_with_end)

    clauses: defaultdict[
        RequirementKind, dict[tuple[str, ...], list[RequirementEvidence]]
    ] = defaultdict(lambda: defaultdict(list))
    unresolved = []
    for (kind, source_surface, start, end, text), items in groups.items():
        surface = _surface(record, source_surface)
        if surface is not None:
            previous_line = next(
                (
                    line.strip()
                    for line in reversed(surface[:start].splitlines())
                    if line.strip()
                ),
                "",
            )
            if _ONE_OF_PRELUDE.fullmatch(previous_line):
                evidence = RequirementEvidence(
                    source_surface=source_surface,
                    char_start=start,
                    char_end=end,
                    text=text,
                    mention_indices=tuple(item.mention_index for item in items),
                )
                unresolved.append(
                    UnresolvedRequirement(
                        requirement_kind=kind,
                        reason=UnresolvedReason.LOGIC_UNSUPPORTED,
                        known_tech_ids=tuple(
                            item.tech_id for item in items if item.tech_id is not None
                        ),
                        raw_operands=(),
                        evidence=evidence,
                    )
                )
                continue
        evidence = RequirementEvidence(
            source_surface=source_surface,
            char_start=start,
            char_end=end,
            text=text,
            mention_indices=tuple(item.mention_index for item in items),
        )
        parsed, unresolved_item = _parse_segment(kind, text, evidence, items)
        for tech_ids, clause_evidence in parsed:
            if tech_ids:
                clauses[kind][tech_ids].append(clause_evidence)
        if unresolved_item is not None:
            unresolved.append(unresolved_item)

    for (kind, source_surface, evidence_text), items in unlocated.items():
        unresolved.append(
            UnresolvedRequirement(
                requirement_kind=kind,
                reason=UnresolvedReason.EVIDENCE_NOT_LOCATED,
                known_tech_ids=tuple(
                    item.tech_id
                    for item in items
                    if item.match_status is MatchStatus.MATCHED
                    and item.tech_id is not None
                ),
                raw_operands=tuple(
                    item.raw_technology
                    for item in items
                    if item.match_status is not MatchStatus.MATCHED
                    or item.tech_id is None
                ),
                evidence=RequirementEvidence(
                    source_surface=source_surface,
                    char_start=None,
                    char_end=None,
                    text=evidence_text,
                    mention_indices=tuple(item.mention_index for item in items),
                ),
            )
        )

    def build_clauses(kind: RequirementKind) -> tuple[RequirementClause, ...]:
        return tuple(
            RequirementClause(
                tech_ids=tech_ids,
                evidence_refs=_merge_evidence(tuple(evidences)),
            )
            for tech_ids, evidences in sorted(clauses[kind].items())
        )

    unresolved = sorted(
        unresolved,
        key=lambda item: (
            item.requirement_kind.value,
            _evidence_sort_key(item.evidence),
            item.reason.value,
            item.known_tech_ids,
            item.raw_operands,
        ),
    )
    return JobRequirements(
        source_record_id=record.source_record_id,
        content_hash=record.content_hash,
        parser_version=JOB_REQUIREMENT_PARSER_VERSION,
        required=build_clauses(RequirementKind.REQUIRED),
        preferred=build_clauses(RequirementKind.PREFERRED),
        unresolved=tuple(unresolved),
    )
